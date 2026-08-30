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
