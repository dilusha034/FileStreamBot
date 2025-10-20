<p align="center">
  <img src="https://raw.githubusercontent.com/dilusha034/FileStreamBot/main/photo_2025-09-24_00-54-09.jpg" alt="POP Tv Logo" width="200">
</p>

<h1 align="center">POP Tv One - File Stream Bot</h1>

<p align="center">
  <b><i>A powerful, customized Telegram bot to generate direct stream links instantly.</i></b>
</p>

<p align="center">
    <a href="https://github.com/dilusha034/FileStreamBot/stargazers">
        <img src="https://img.shields.io/github/stars/dilusha034/FileStreamBot?style=social" alt="Stars">
    </a>
    <a href="https://github.com/dilusha034/FileStreamBot/network/members">
        <img src="https://img.shields.io/github/forks/dilusha034/FileStreamBot?style=social" alt="Forks">
    </a>
</p>

---

### 🚀 About This Project

This is a customized and enhanced version of the popular FileStreamBot, proudly maintained by **POP Tv One**. This bot allows you to generate direct streamable links for any file stored on Telegram, eliminating the need to download files before watching. It's fast, efficient, and perfect for media lovers!

### ✨ Key Features

-   **Instant Streaming:** Get direct links for your Telegram files in seconds.
-   **No Download Needed:** Play your videos and media directly in your browser or media player.
-   **Channel Support:** Fully supports files from Telegram channels.
-   **Easy Deployment:** Deploy your own instance of the bot on Heroku, VPS, or using Docker.
-   **Highly Customizable:** You can easily configure the bot with your own settings and variables.

---

### 🛠️ Deployment Guide

You can deploy this bot on various platforms. Choose the method that suits you best.

<br>
<details>
  <summary><b>Deploy on Heroku (Paid)</b></summary>
  <br>
  <ul>
    <li>Fork This Repository: <a href="https://github.com/dilusha034/FileStreamBot/fork">Click Here</a></li>
    <li>Click on the Deploy button below to get started on Heroku.</li>
  </ul>
  <a href="https://heroku.com/deploy?template=https://github.com/dilusha034/FileStreamBot">
    <img src="https://www.herokucdn.com/deploy/button.svg" alt="Deploy">
  </a>
  <br>
  <em>Go to the <a href="#-configuration-variables">Configuration section</a> for more info on setting up environmental variables.</em>
</details>

<details>
  <summary><b>Deploy Locally / on VPS</b></summary>
  <br>
  <p>Follow these commands to run the bot on your local machine or a Virtual Private Server (VPS).</p>
  <pre><code># Clone your repository (NOT the original one)
git clone https://github.com/dilusha034/FileStreamBot
cd FileStreamBot

# Create a virtual environment and activate it
python3 -m venv ./venv
. ./venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the bot
python3 -m FileStream</code></pre>
  <p>To stop the bot, press <kbd>CTRL</kbd> + <kbd>C</kbd>.</p>
  <p>To run the bot 24/7 on a VPS, use <code>tmux</code>:</p>
  <pre><code>sudo apt install tmux -y
tmux
python3 -m FileStream</code></pre>
  <p>Now you can safely close the VPS terminal, and the bot will continue to run.</p>
</details>

<details>
  <summary><b>Deploy using Docker</b></summary>
  <br>
  <p>Clone the repository:</p>
  <pre><code>git clone https://github.com/dilusha034/FileStreamBot
cd FileStreamBot</code></pre>
  <p>Build your Docker image:</p>
  <pre><code>docker build -t pop-tv-filestream .</code></pre>
  <p>Create an <code>.env</code> file with your variables, then start the container:</p>
  <pre><code>docker run -d --restart unless-stopped --name pop-tv-bot \
-v /path/to/your/.env:/app/.env \
-p 8080:8080 \
pop-tv-filestream</code></pre>
  <p>To restart the container after changing variables, use:</p>
  <pre><code>docker restart pop-tv-bot</code></pre>
</details>

---

### ⚙️ Configuration (Variables)

<details>
  <summary><b>Click to see all required and optional variables</b></summary>
  <br>
  <p>If you're on Heroku, add these in the 'Config Vars' section. If you're hosting locally, create a file named <code>.env</code> and add them there.</p>

  <h4>📝 Mandatory Vars:</h4>
  <ul>
    <li><code>API_ID</code>: Get from my.telegram.org.</li>
    <li><code>API_HASH</code>: Get from my.telegram.org.</li>
    <li><code>OWNER_ID</code>: Your Telegram User ID.</li>
    <li><code>BOT_TOKEN</code>: Your bot's token from @BotFather.</li>
    <li><code>DATABASE_URL</code>: Your MongoDB connection URI.</li>
    <li>And other required variables as listed in the original documentation...</li>
  </ul>
  
  <h4>🪐 Optional Vars:</h4>
  <ul>
    <li><code>UPDATES_CHANNEL</code>, <code>FORCE_SUB_ID</code>, <code>START_PIC</code>, etc., can be configured for a better user experience.</li>
  </ul>
</details>

---

### 💬 Get in Touch

Have questions, suggestions, or need help with this specific version? Feel free to reach out to me!

-   **Telegram:** **[@Mr_D_2000](https://t.me/Mr_D_2000)**

### ❤️ Acknowledgements & Credits

This project is a customized fork of the original **[FileStreamBot](https://github.com/avipatilpro/FileStreamBot)**. A huge thank you to the original developers for their incredible work and for making their code open-source.

-   [**AvishkarPatil (avipatilpro)**](https://github.com/AvishkarPatil) - For the original bot.
-   [**Deekshith SH**](https://github.com/DeekshithSH) - For modules.
-   [**EverythingSuckz**](https://github.com/EverythingSuckz) - For his version of FileStreamBot.
-   [**Biisal**](https://github.com/biisal) - For the Stream Page UI.

---

<p align="center">
  <b>© 2025 POP Tv One | Maintained by <a href="https://t.me/Mr_D_2000">Dilusha</a></b>
</p>
