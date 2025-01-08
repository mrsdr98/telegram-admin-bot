#!/bin/bash

# setup.sh - Automated installation script for Telegram Admin Bot

# Exit immediately if a command exits with a non-zero status
set -e

# Functions to display messages
function echo_info() {
    echo -e "\e[32m[INFO]\e[0m $1"
}

function echo_error() {
    echo -e "\e[31m[ERROR]\e[0m $1"
}

# Update and upgrade the system
echo_info "Updating and upgrading the system..."
sudo apt update && sudo apt upgrade -y

# Install necessary packages
echo_info "Installing necessary packages..."
sudo apt install -y python3 python3-pip python3-venv git ufw

# Configure firewall
echo_info "Configuring UFW firewall..."
sudo ufw allow OpenSSH
sudo ufw --force enable
sudo ufw status

# Create dedicated user if not exists
USERNAME="telegrambot"
if id "$USERNAME" &>/dev/null; then
    echo_info "User '$USERNAME' already exists."
else
    echo_info "Creating user '$USERNAME'..."
    sudo adduser --disabled-password --gecos "" $USERNAME
    sudo usermod -aG sudo $USERNAME
fi

# Clone the repository if not already cloned
REPO_DIR="/home/$USERNAME/telegram-admin-bot"
if [ -d "$REPO_DIR" ]; then
    echo_info "Repository already cloned."
else
    echo_info "Cloning the repository..."
    sudo -u $USERNAME git clone https://github.com/mrsdr98/telegram-admin-bot.git $REPO_DIR
fi

# Navigate to the project directory
cd $REPO_DIR

# Create a virtual environment
echo_info "Creating a Python virtual environment..."
sudo -u $USERNAME python3 -m venv venv

# Activate the virtual environment and install dependencies
echo_info "Installing Python dependencies..."
sudo -u $USERNAME bash -c "source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt"

# Configure environment variables
ENV_FILE=".env"
if [ -f "$ENV_FILE" ]; then
    echo_info "The .env file already exists."
else
    echo_info "Creating the .env file with user input..."
    # Prompt user for environment variables
    read -p "Enter your Telegram bot token (BOT_TOKEN): " BOT_TOKEN_INPUT
    read -p "Enter your Telegram API ID (API_ID): " API_ID_INPUT
    read -p "Enter your Telegram API Hash (API_HASH): " API_HASH_INPUT
    read -p "Enter your Telegram phone number (PHONE_NUMBER) [include country code, e.g., +15555555555]: " PHONE_NUMBER_INPUT
    read -p "Enter admin user IDs (comma-separated, e.g., 123456789,987654321): " ADMIN_USERS_INPUT

    # Create the .env file with the provided inputs
    sudo -u $USERNAME bash -c "cat > $ENV_FILE << EOL
BOT_TOKEN=$BOT_TOKEN_INPUT
API_ID=$API_ID_INPUT
API_HASH=$API_HASH_INPUT
PHONE_NUMBER=$PHONE_NUMBER_INPUT
ADMIN_USERS=$ADMIN_USERS_INPUT
EOL"

    echo_info ".env file created successfully."
fi

# Secure the .env file
echo_info "Securing the .env file..."
sudo chown $USERNAME:$USERNAME $ENV_FILE
sudo chmod 600 $ENV_FILE

# Create directories for logs and photos
echo_info "Creating directories for logs and photos..."
sudo -u $USERNAME mkdir -p logs photos

# Create systemd service file
SERVICE_FILE="/etc/systemd/system/telegrambot.service"
if [ -f "$SERVICE_FILE" ]; then
    echo_info "systemd service file already exists."
else
    echo_info "Creating systemd service file..."
    sudo bash -c "cat > $SERVICE_FILE << EOL
[Unit]
Description=Telegram Admin Bot
After=network.target

[Service]
User=$USERNAME
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/venv/bin/python $REPO_DIR/telegram_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL"
    echo_info "Reloading systemd daemon..."
    sudo systemctl daemon-reload

    echo_info "Enabling and starting the Telegram Admin Bot service..."
    sudo systemctl enable telegrambot
    sudo systemctl start telegrambot

    echo_info "Checking the service status..."
    sudo systemctl status telegrambot --no-pager
fi

echo_info "Installation completed successfully!"
echo_info "To view logs, use: sudo journalctl -u telegrambot -f"
echo_info "To stop the bot, use: sudo systemctl stop telegrambot"
echo_info "To restart the bot, use: sudo systemctl restart telegrambot"
