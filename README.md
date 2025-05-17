# 📅 EduSync

A Telegram bot that automatically syncs your Quera/CW assignments with Google Calendar, helping you stay organized and never miss a deadline.

## 🌟 Features

- **Easy Setup**: Simple two-step authentication process for both Quera and Google Calendar
- **Automatic Syncing**: Option to automatically sync assignments every 3 hours
- **Manual Control**: Sync on demand whenever you want
- **Smart Updates**: Only adds new assignments and updates existing ones
- **Status Tracking**: Clear visual indicators for connection status
- **User-Friendly Interface**: Intuitive button-based navigation

## ✅ TODOs
- [ ] Write Privacy Policy For Google
- [ ] Deploy
- [ ] Get User Feedback !
- [ ] Add SQL DB
- [ ] Add CW Feature
- [ ] Add User:Pass Login Option For CW
- [ ] Add Admin Dashboard or CMS

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- A Telegram account
- A Google account
- A Quera account

### Installation

1. Clone the repository:
```bash
git clone https://github.com/erfnzdeh/quera-to-google-calendar-automation.git
cd quera-to-google-calendar-automation
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables in `.env`:
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
```

5. Run the bot:
```bash
python main.py
```

## 📱 Using the Bot

1. Start the bot by sending `/start` in Telegram
2. Connect your accounts:
   - Click "🔗 Connect Calendar" to connect Google Calendar
   - Click "🔗 Connect Quera" to connect your Quera account
3. Access sync options:
   - Use "⚙️ Sync Options" to view sync menu
   - Choose between manual sync or enable auto-sync

### Sync Options

- **🔄 Sync Now**: Manually sync your assignments
- **⏱️ Toggle Auto Sync**: Enable/disable automatic syncing every 3 hours
- **↩️ Back to Main Menu**: Return to the main menu

## 🔑 Getting Your Quera Session ID

1. Log in to [Quera](https://quera.org)
2. Open browser's developer tools (F12)
3. Go to Application/Storage > Cookies
4. Find and copy the value of 'session_id'

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📞 Support

For support or feedback:
1. Visit our [GitHub repository](https://github.com/erfnzdeh/quera-to-google-calendar-automation)
2. Open an issue for bug reports or feature requests
3. Contact directly: [@Pouri2048](https://t.me/Pouri2048)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.