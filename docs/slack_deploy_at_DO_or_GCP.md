# Deploy the PinionAI Slack bot on a VM

This is the recommended production path for the Slack integration because the bot runs a long-lived Socket Mode connection and keeps state in memory. A VM is usually a better fit than Cloud Run for this workload.

## Why a VM is a better fit

- The bot must stay connected to Slack continuously.
- Cloud Run is designed for short-lived HTTP requests and can scale to zero.
- A VM gives you predictable uptime, easier restarts, and better logs.
- This is usually cheaper than paying for a fully managed service for a single always-on bot.

## Recommended approach

Use a Debian 12 or Ubuntu 22.04 VM and run the bot as a systemd service.

You do not need Node.js or npm for this project. The Slack bot is a Python application.

---

## Option A: DigitalOcean Droplet (recommended for cost)

### 1. Create the droplet

- Create a Debian 12 or Ubuntu 22.04 droplet.
- Choose at least 2 GB RAM if you expect regular traffic.
- Add SSH keys and create a non-root user if you want a more secure setup.

### 2. Secure the server

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ufw fail2ban
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 3. Install Python and build tools

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl build-essential nginx certbot python3-certbot-nginx
python3 --version
pip3 --version
```

### 4. Clone the project

```bash
cd /home/your-user
git clone https://github.com/pinionai/pinionai-streamlit-agent.git
cd pinionai-streamlit-agent
```

### 5. Create a Python virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

If the repository uses uv in your environment, you can also use:

```bash
uv pip sync requirements.txt
```

### 6. Create the environment file

```bash
cp .env.example .env 2>/dev/null || touch .env
chmod 600 .env
nano .env
```

Add values similar to:

```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
host_url=https://api.pinionai.com
client_id=...
client_secret=...
agent_id=...
```

### 7. Run the bot manually once to verify it starts

```bash
source .venv/bin/activate
python chat_slack.py
```

### 8. Install it as a systemd service

Create a service file:

```bash
sudo nano /etc/systemd/system/pinionai-slack.service
```

Add:

```ini
[Unit]
Description=PinionAI Slack Bot
After=network.target

[Service]
WorkingDirectory=/home/your-user/pinionai-streamlit-agent
EnvironmentFile=/home/your-user/pinionai-streamlit-agent/.env
ExecStart=/home/your-user/pinionai-streamlit-agent/.venv/bin/python chat_slack.py
Restart=always
RestartSec=5
User=your-user
Group=your-user
StandardOutput=append:/var/log/pinionai-slack.log
StandardError=append:/var/log/pinionai-slack.err.log

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pinionai-slack
sudo systemctl start pinionai-slack
sudo systemctl status pinionai-slack
```

### 9. Optional: add Nginx and HTTPS

If you want a public web endpoint for health checks or future web features, configure Nginx and Certbot.

```bash
sudo certbot --nginx -d slack.yourdomain.com
```

For this bot specifically, the main requirement is the systemd service above. Nginx is optional.

---

## Option B: Google Compute Engine VM

The same approach works well on Google Compute Engine.

### 1. Create a VM

- Use Debian 12 or Ubuntu 22.04.
- Allow SSH and optionally HTTP/HTTPS traffic.
- Use a static external IP if you expect stable access.

### 2. Install the same Python stack

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git curl build-essential nginx certbot python3-certbot-nginx
```

### 3. Clone the repo, set up the environment, and install the service

Follow the same steps as above for cloning, creating the virtual environment, populating the `.env` file, and creating the systemd service.

### 4. Firewall rules

In Google Cloud, make sure the VM allows:

- TCP 22 for SSH
- TCP 80 and 443 if you use Nginx/HTTPS

---

## Operational notes

- Monitor logs with:

```bash
sudo journalctl -u pinionai-slack -f
```

- Restart the service with:

```bash
sudo systemctl restart pinionai-slack
```

- If you change the environment variables, restart the service so the new values are picked up.

## Recommendation

For this Slack bot, a VM-based deployment is the most reliable path. DigitalOcean is a strong low-cost option. Google Compute Engine is a good choice if you want to stay inside the Google ecosystem.

These steps describe how to update the running application on your Digital Ocean server.

1.  **Navigate to your project directory:**

    ```bash
    cd pinionai-streamlit-agent
    ```

2.  **Pull the latest changes from Git:**

    ```bash
    git pull
    ```

3.  **Install/update dependencies (if needed):**

    ```bash
    sudo npm install
    ```

4.  **Stop and remove the old Docker container:**

    ```bash
    # The container was likely named 'pinionai-slack'. These commands will stop and remove it.
    # Use 'docker ps' to verify the container name or ID if needed.
    docker stop pinionai-slack
    docker rm pinionai-slack

    docker stop <container_id>
    docker rm <container_id>

    ```

5.  **Rebuild the Docker image with the latest code:**

    ```bash
    docker build --no-cache -t pinionai-slack .

    # or

    docker build -t pinionai-slack .
    ```

6.  **Run the new container:**

    ```bash
    docker run -p 3000:3000 pinionai-slack
    ```

7.  **Reload Nginx (if needed):**

```bash
sudo systemctl reload nginx
```

8. **Clean up old Docker images (Optional):**

Over time, you may accumulate old, unused Docker images. You can clean them up with this command.

```bash
docker image prune -f
```
