# Project Setup Guide

Ye document project ko scratch se set up karne ke sare steps cover karta hai — git init se lekar GitHub pe push karne tak.

## 1. Folder banao aur git init karo

```bash
mkdir self-healing-sql-agent
cd self-healing-sql-agent
git init
```

## 2. Git user email set karo

```bash
git config user.email nitish@thinkcurve.in
```

## 3. Folder structure banao

```bash
mkdir -p backend/app frontend
touch backend/requirements.txt
touch backend/Dockerfile
touch frontend/Dockerfile
touch docker-compose.yml
touch README.md
touch .gitignore
```

## 4. .gitignore banao

```bash
cat > .gitignore << 'EOF'
venv/
__pycache__/
*.pyc
node_modules/
dist/
.env
*.db
EOF
```

## 5. README likho

```bash
echo "# Self-Healing Data Query Agent" > README.md
```

## 6. Pehla commit karo

```bash
git add .
git commit -m "Initial project structure"
```

## 7. Main branch rename karo

```bash
git branch -M main
```

## 8. Remote add karo (SSH alias ke saath)

Agar `~/.ssh/config` me multiple GitHub accounts ke liye alias set hai (jaise `github-personal`), toh remote SSH format me set karo — `https://` mat use karo alias ke saath, warna URL galat parse hoga.

```bash
git remote add origin git@github-personal:Nitishjha7/self-healing-sql-agent.git
```

Agar SSH alias set nahi hai, seedha HTTPS use karo (push ke time username + Personal Access Token maangega):

```bash
git remote add origin https://github.com/Nitishjha7/self-healing-sql-agent.git
```

## 9. Push karo

```bash
git push -u origin main
```

## Common Error: "Port number was not a decimal number"

Agar ye error aaye:

```
fatal: unable to access 'https://github-personal:Nitishjha7/...': URL rejected: Port number was not a decimal number between 0 and 65535
```

Iska matlab hai SSH alias (`github-personal`) galti se `https://` URL ke saath mix ho gaya hai. Fix:

```bash
git remote remove origin
git remote add origin git@github-personal:Nitishjha7/self-healing-sql-agent.git
git push -u origin main
```

## Common Error: "Repository not found"

Iska matlab GitHub pe repo abhi tak create nahi hua ya SSH key register nahi hui. Pehle browser me jaake GitHub pe naya empty repo banao (bina README/gitignore), phir dobara push karo.

---

# Naye Project ke liye Template (e.g. code-guardian)

Naye project ke liye same steps repeat karne honge, bas naam change karke.

### Step 1: Naya folder + git init

```bash
cd ~/Music
mkdir code-guardian
cd code-guardian
git init
```

### Step 2: Folder structure banao

```bash
mkdir -p backend/app/agents
mkdir -p backend/app/mcp_clients
mkdir -p backend/app/guardrails_config
mkdir -p frontend/src

touch backend/requirements.txt
touch backend/Dockerfile
touch backend/app/__init__.py
touch backend/app/graph.py
touch backend/app/agents/security_agent.py
touch backend/app/agents/performance_agent.py
touch backend/app/agents/patch_generator.py
touch backend/app/agents/supervisor.py
touch frontend/Dockerfile
touch docker-compose.yml
touch README.md
touch .gitignore
```

### Step 3: .gitignore banao

```bash
cat > .gitignore << 'EOF'
venv/
__pycache__/
*.pyc
node_modules/
dist/
.env
*.db
*.log
EOF
```

### Step 4: README likho

```bash
echo "# Code Guardian — Multi-Agent Autonomous Code Reviewer & PR Bot" > README.md
```

### Step 5: Git config check

```bash
git config user.email nitishkj5019@gmail.com
```

### Step 6: Main branch + pehla commit

```bash
git branch -M main
git add .
git commit -m "Initial project scaffold - Code Guardian"
```

### Step 7: GitHub pe naya repo banao

Browser me jaake naam se naya empty repo banao (bina README/gitignore).

### Step 8: Remote add karo aur push karo

```bash
git remote add origin git@github-personal:Nitishjha7/code-guardian.git
git push -u origin main
```

### Step 9 (Optional): Phase-wise branches banao

```bash
git checkout -b feature/phase-1-local-review-studio
git push -u origin feature/phase-1-local-review-studio

git checkout main
git checkout -b feature/phase-2-github-mcp-integration
git push -u origin feature/phase-2-github-mcp-integration

git checkout main
```
