# AI Procurement Assistant Demo

Streamlit demo for an AI-assisted procurement decision workflow. The app lets a business user enter a natural-language procurement request, then generates a budget-compliant procurement plan with replenishment, growth opportunities, inventory risks, and price trend signals.

## Features

- Natural-language procurement request parsing with DeepSeek, with local fallback parsing when AI is not configured.
- Budget-aware recommendation plan.
- Recommended replenishment based on order history, inventory coverage, shelf life, holidays, favorites, and context.
- Growth opportunity trial buys.
- Product price trend signals from the `PriceHistory` Excel sheet.
- Procurement decision report with summary, product table, reasons, and executive notes.

## Documentation

- [Customer Demo Guide](CUSTOMER_DEMO_GUIDE.md)
- [Demo Lessons and Recommendation Logic Guide](docs/DEMO_LESSONS_AND_RECOMMENDATION_GUIDE.md)

## Local Run

```bash
cd "/Users/carrie/Documents/ai/recommend demo"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.port 8501
```

Open:

```text
http://localhost:8501
```

## Configuration

Use environment variables for secrets and deployment-specific paths.

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export EXCEL_FILE="/absolute/path/to/data/AI_Demo_Data_Pack_V2_Large.xlsx"
streamlit run app.py --server.port 8501
```

Available variables:

- `APP_TITLE`
- `LOG_LEVEL`
- `AI_ENABLED`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `AI_TEMPERATURE`
- `AI_MAX_TOKENS`
- `EXCEL_FILE`

Never commit real API keys. Use `.env.example` as a template only.

## Tencent Cloud CVM Deployment

Recommended deployment pattern:

```text
Tencent Cloud CVM
Ubuntu 22.04
Python venv
Streamlit on port 8501
systemd service
Nginx reverse proxy on port 80/443
```

### 1. Install Server Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
```

### 2. Upload Project

From your local machine:

```bash
scp -r "/Users/carrie/Documents/ai/recommend demo" ubuntu@YOUR_SERVER_IP:/home/ubuntu/recommend-demo
```

Or clone from Git:

```bash
git clone YOUR_REPO_URL /home/ubuntu/recommend-demo
```

### 3. Install Python Dependencies

```bash
cd /home/ubuntu/recommend-demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure systemd

Copy and edit the service template:

```bash
sudo cp deploy/procurement-demo.service /etc/systemd/system/procurement-demo.service
sudo nano /etc/systemd/system/procurement-demo.service
```

Replace:

- `User=ubuntu` if your server user is different.
- `/home/ubuntu/recommend-demo` if your project path is different.
- `DEEPSEEK_API_KEY=replace-with-your-deepseek-api-key`.

Start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable procurement-demo
sudo systemctl start procurement-demo
sudo systemctl status procurement-demo
```

Check logs:

```bash
sudo journalctl -u procurement-demo -f
```

### Server Operations

Current Tencent Cloud deployment:

```text
Server: 43.166.153.217
Project path: /home/ubuntu/recommend-demo
Service name: procurement-demo
Public URL: http://43.166.153.217
```

SSH into the server:

```bash
ssh ubuntu@43.166.153.217
```

Restart the Streamlit application:

```bash
sudo systemctl restart procurement-demo
```

Check application status:

```bash
sudo systemctl status procurement-demo
```

View live application logs:

```bash
sudo journalctl -u procurement-demo -f
```

View recent application logs:

```bash
sudo journalctl -u procurement-demo -n 100 --no-pager
```

Restart Nginx after proxy configuration changes:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Check Nginx status:

```bash
sudo systemctl status nginx
```

Update DeepSeek key on the server:

```bash
sudo nano /etc/procurement-demo.env
sudo systemctl restart procurement-demo
```

Confirm DeepSeek key is configured without printing the key:

```bash
sudo grep -q '^DEEPSEEK_API_KEY=.' /etc/procurement-demo.env && echo "DeepSeek key configured"
```

Validate the public site:

```bash
curl -I http://43.166.153.217
```

Run tests on the server:

```bash
cd /home/ubuntu/recommend-demo
PYTHONPYCACHEPREFIX=/tmp/python-cache .venv/bin/python -m unittest tests/test_recommendation_engine.py
```

### 5. Configure Nginx

Copy and edit the Nginx template:

```bash
sudo cp deploy/nginx-procurement-demo.conf /etc/nginx/sites-available/procurement-demo
sudo nano /etc/nginx/sites-available/procurement-demo
```

Replace:

```nginx
server_name your-domain.com;
```

with your domain or server public IP.

Enable Nginx config:

```bash
sudo ln -s /etc/nginx/sites-available/procurement-demo /etc/nginx/sites-enabled/procurement-demo
sudo nginx -t
sudo systemctl reload nginx
```

Then visit:

```text
http://YOUR_SERVER_IP
```

or:

```text
http://YOUR_DOMAIN
```

### 6. HTTPS Optional

If you have a domain:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_DOMAIN
```

## Tencent Cloud Security Group

Open these ports:

- `22` for SSH
- `80` for HTTP
- `443` for HTTPS
- `8501` only if you want direct Streamlit access during testing

For production-style demos, expose only `80/443` and keep `8501` internal behind Nginx.

## Workbook

Default workbook:

```text
data/AI_Demo_Data_Pack_V2_Large.xlsx
```

Important sheets:

- `Customer`
- `Product`
- `OrderHistory`
- `Inventory`
- `Favorites`
- `IndustryTrend`
- `HolidayConfig`
- `HolidayProduct`
- `ConversationContext`
- `PriceHistory`
