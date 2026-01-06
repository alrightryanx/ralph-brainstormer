import argparse
import subprocess
import os
import sys
import time
import re
import json
import logging
from datetime import datetime

# --- Configuration ---
PLANS_DIR = "plans"
RALPH_DIR = os.path.join(PLANS_DIR, "ralph_brainstorm")

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RalphBrainstormer")

def clean_output(text):
    """Removes ANSI codes and excess whitespace."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\-_]| [0-?]*[@-~])')
    return ansi_escape.sub('', text).strip()

def call_cli(cli_name, prompt, context_files=None, retries=3, delay=20):
    """
    Executes the specified CLI with exponential backoff for rate limits.
    """
    logger.info(f"[{cli_name.upper()}] Thinking...")
    
    full_prompt = prompt
    if context_files:
        full_prompt += "\n\n--- CONTEXT FROM FILES ---"
        for cf in context_files:
            if os.path.exists(cf):
                with open(cf, 'r', encoding='utf-8') as f:
                    full_prompt += f"\nFile: {os.path.basename(cf)}\n{f.read()}\n"
    
    command = []
    if cli_name == "claude":
        command = ["claude", full_prompt]
    elif cli_name == "gemini":
        if os.path.exists("gemini.ps1"):
            command = ["powershell", "-NoProfile", "-File", "gemini.ps1", full_prompt]
        else:
            command = ["gemini", full_prompt]
    elif cli_name == "codex":
        command = ["gemini", f"SIMULATE CODEX: {full_prompt}"]

    for attempt in range(retries):
        try:
            result = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                encoding='utf-8', 
                timeout=240, 
                shell=True if os.name == 'nt' else False
            )
            
            output = clean_output(result.stdout)
            errors = result.stderr.lower()
            
            # Rate Limit Detection
            is_limited = any(x in errors or x in output.lower() for x in 
                            ["rate limit", "429", "too many requests", "overloaded", "try again in"])
            
            if is_limited:
                wait_time = delay * (2 ** attempt)
                logger.warning(f"[{cli_name.upper()}] Rate limited. Retrying in {wait_time}s... (Attempt {attempt+1}/{retries})")
                time.sleep(wait_time)
                continue

            if result.returncode != 0 and not is_limited:
                return f"Error generating plan with {cli_name}: {result.stderr}"
                
            return output

        except Exception as e:
            if attempt == retries - 1:
                return f"Exception: {str(e)}"
            time.sleep(delay)
            
    return f"Error: {cli_name.upper()} is consistently rate limited. Skipping."

def save_md(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Saved: {path}")

def get_rankings(clis, plans, objective):
    """Asks multiple CLIs to rank a list of plans."""
    all_plans_text = ""
    for d in plans:
        all_plans_text += f"\n\n=== PLAN ID: {d['id']} ===\n{d['content'][:800]}...\n"
    
    ranking_prompt = f"Objective: {objective}\n\nReview these plans. Rank them based on technical feasibility, scalability, and depth. Return ONLY JSON: {{ 'rank': ['id1', 'id2', ...] }}\n\n{all_plans_text}"
    
    votes = {}
    for cli in clis:
        resp = call_cli(cli, ranking_prompt)
        try:
            json_match = re.search(r'{{.*}}', resp, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                rank_list = data.get('rank', [])
                for idx, pid in enumerate(rank_list):
                    # Borda count: 1st place gets max points (len(plans))
                    votes[pid] = votes.get(pid, 0) + (len(plans) - idx)
        except:
            logger.warning(f"[{cli}] Ranking parse failed or no JSON returned.")
    
    return sorted(votes.items(), key=lambda x: x[1], reverse=True)

def run_brainstorm(project_name, objective):
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(RALPH_DIR, project_name, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    clis = ["claude", "gemini", "codex"]
    
    # 1. GENERATE 9 DRAFTS
    logger.info("PHASE 1: Generating 9 Initial Plans (3 Rounds x 3 CLIs)...")
    drafts = []
    for i in range(1, 4):
        logger.info(f"Drafting Round {i}...")
        round_failures = 0
        for cli in clis:
            plan = call_cli(cli, f"Draft #{i} for '{project_name}'. Objective: {objective}. Provide a full technical roadmap.")
            if "consistently rate limited" in plan:
                round_failures += 1
                
            path = os.path.join(session_dir, f"round{i}-draft-{cli}.md")
            save_md(path, plan)
            drafts.append({"id": f"{cli}-R{i}", "content": plan, "path": path})
        
        if round_failures == len(clis):
            logger.warning("!!! ALL MODELS RATE LIMITED !!! Entering 2-minute cool down...")
            time.sleep(120)

    # 2. RANKING ROUND 1 (Find Top 3)
    logger.info("PHASE 2: Ranking Initial Drafts...")
    sorted_ids = get_rankings(clis, drafts, objective)
    top_3_ids = [x[0] for x in sorted_ids[:3]]
    top_3_plans = [d for d in drafts if d['id'] in top_3_ids]
    logger.info(f"Top 3 Selected: {top_3_ids}")

    # 3. ENHANCEMENT
    logger.info("PHASE 3: Enhancing Top 3 Winners...")
    enhanced = []
    for i, plan in enumerate(top_3_plans):
        cli = clis[i % len(clis)]
        new_content = call_cli(cli, f"You are refining a Top Pick Plan. Expand it into a comprehensive Master Plan with architecture, dependencies, and risks.\n\nOriginal Content:\n{plan['content']}")
        path = os.path.join(session_dir, f"enhanced-{plan['id']}.md")
        save_md(path, new_content)
        enhanced.append({"id": f"Eh-{plan['id']}", "content": new_content, "path": path})

    # 4. AGENT DEBATE (Generate 6 NEW PLANS)
    logger.info("PHASE 4: Starting Multi-Turn Agent A/B Debates...")
    debate_pool = []
    for plan in enhanced:
        logger.info(f"Debating Plan: {plan['id']}")
        
        # Turn 1: Agent A asks questions
        questions = call_cli("claude", "Analyze this plan. Ask 3 critical technical questions to the lead engineer (Agent B).", context_files=[plan['path']])
        
        # Turn 2: Agent B answers
        answers = call_cli("gemini", f"You are Agent B. Answer these questions from Agent A regarding the plan:\n{questions}", context_files=[plan['path']])
        
        # Turn 3: Agent A responds to the answers
        response_a = call_cli("claude", f"Agent B provided these answers. Respond to them with any remaining concerns or critiques:\n{answers}", context_files=[plan['path']])
        
        # Turn 4: Agent B reflects (No response) and improves the plan
        # This creates the first of the 2 new plans for this parent
        rev_b = call_cli("gemini", f"Analyze Agent A's critique of your answers. Without responding back, incorporate all feedback and produce your own improved version of the Master Plan.\nCritique:\n{response_a}", context_files=[plan['path']])
        
        # Turn 5: Agent A sees the revised plan and makes their own version
        rev_a = call_cli("claude", f"Agent B has revised the plan based on your critique. Now, create YOUR own definitive version of this Master Plan.\nAgent B's Revised Version:\n{rev_b}", context_files=[plan['path']])
        
        path_a = os.path.join(session_dir, f"debate-A-{plan['id']}.md")
        path_b = os.path.join(session_dir, f"debate-B-{plan['id']}.md")
        save_md(path_a, rev_a)
        save_md(path_b, rev_b)
        
        debate_pool.extend([
            {"id": f"RevA-{plan['id']}", "content": rev_a, "path": path_a},
            {"id": f"RevB-{plan['id']}", "content": rev_b, "path": path_b}
        ])

    # 5. FINAL RANKING (3 Enhanced + 6 Debate = 9 Plans)
    logger.info("PHASE 5: Final Ranking of the 9 Best Plans...")
    final_pool = enhanced + debate_pool
    final_rankings = get_rankings(clis, final_pool, objective)
    winner_id = final_rankings[0][0]
    winner = next(p for p in final_pool if p['id'] == winner_id)

    # 6. FINAL SELECTION & DECISION
    logger.info(f"PHASE 6: Final Decision. Winner: {winner_id}")
    master_path = os.path.join(RALPH_DIR, project_name, "FINAL_MASTER_PLAN.md")
    
    # Final analysis by all 3 CLIs on the winner
    approvals = []
    for cli in clis:
        check = call_cli(cli, f"This is the winning plan. Is it ready for implementation? Provide a brief final verdict and say 'APPROVED' if it is solid.\n\n{winner['content']}")
        approvals.append(f"### {cli.upper()} Verdict:\n{check}")
    
    final_content = f"""# FINAL MASTER PLAN: {project_name}
## Winner ID: {winner_id}
## Strategy: Multi-Agent Debate & Consensus

{winner['content']}

---
## Final Consensus Decisions:
{"\n\n".join(approvals)}
"""
    save_md(master_path, final_content)
    print(f"\n[SUCCESS] Ralph Brainstormer complete.")
    print(f"Master Plan saved to: {master_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ralph Mode Brainstorming Engine")
    parser.add_argument("--project", required=True, help="Name of the project")
    parser.add_argument("--objective", required=True, help="Goal or prompt for the planning session")
    args = parser.parse_args()
    
    run_brainstorm(args.project, args.objective)
