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

def call_cli(cli_name, prompt, context_files=None):
    """
    Executes the specified CLI. 
    Simulates /clear by running a fresh process for each call.
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
        # Placeholder: Using Gemini to simulate Codex if codex CLI isn't installed
        command = ["gemini", f"SIMULATE CODEX: {full_prompt}"]

    try:
        result = subprocess.run(
            command, 
            capture_output=True, 
            text=True, 
            encoding='utf-8', 
            timeout=240, 
            shell=True if os.name == 'nt' else False
        )
        
        if result.returncode != 0:
            return f"Error generating plan with {cli_name}: {result.stderr}"
            
        return clean_output(result.stdout)

    except Exception as e:
        return f"Exception: {str(e)}"

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
        for cli in clis:
            plan = call_cli(cli, f"Draft #{i} for '{project_name}'. Objective: {objective}. Provide a full technical roadmap.")
            path = os.path.join(session_dir, f"round{i}-draft-{cli}.md")
            save_md(path, plan)
            drafts.append({"id": f"{cli}-R{i}", "content": plan, "path": path})

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
    logger.info("PHASE 4: Starting Agent A/B Debates...")
    debate_pool = []
    for plan in enhanced:
        logger.info(f"Debating Plan: {plan['id']}")
        # Agent A (Claude) Critics
        questions = call_cli("claude", "Analyze this plan. Ask 3 extremely critical technical questions about its weaknesses.", context_files=[plan['path']])
        
        # Agent B (Gemini) Answers
        answers = call_cli("gemini", f"As a lead engineer, answer these 3 critical questions for the plan:\n{questions}", context_files=[plan['path']])
        
        # Both Revise based on the exchange
        rev_a = call_cli("claude", f"Based on these answers, rewrite the original plan to be bulletproof:\nAnswers:\n{answers}", context_files=[plan['path']])
        rev_b = call_cli("gemini", f"Create your own improved version of the plan incorporating your answers:\nAnswers:\n{answers}", context_files=[plan['path']])
        
        path_a = os.path.join(session_dir, f"debate-A-{plan['id']}.md")
        path_b = os.path.join(session_dir, f"debate-B-{plan['id']}.md")
        save_md(path_a, rev_a)
        save_md(path_b, rev_b)
        
        debate_pool.extend([
            {"id": f"Deb-A-{plan['id']}", "content": rev_a, "path": path_a},
            {"id": f"Deb-B-{plan['id']}", "content": rev_b, "path": path_b}
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
