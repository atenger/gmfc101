# GMFC101 – Farcaster AI Bot Framework

GMFC101 is an AI assistant that answers questions based on podcast and video transcripts. Built for the GM Farcaster Network, it uses a retrieval-augmented generation (RAG) approach to help users discover content in a conversational way.

> 💬 Ask a question → the bot finds relevant transcript snippets → generates a helpful answer.

---

## 🧠 What It Does

- Analyzes user question to deterimine which route is best for answering:
  - Route 1: Queries a vector database (Pinecone) across all episodes for relevant transcript embeddings
  - Route 2: Retrieves full transcript for 1 single episode from disk
  - Route 3: Retrieves show metadata as context if user asks question that can be answered with show data instead of transcripts
- Uses OpenAI GPT-4-turbo for answer generation
- Designed to support educational or media content archives

This repo includes the core bot logic and sample data to help you run and extend it.

---

## 🛑 Disclaimer

This repository includes **sample transcript data only.**  
The full set of GM Farcaster Network transcripts has not been made publicly available.
If you are interested in using them, please reach out.

If you're building your own bot, replace the sample data with your own content in the format provided and provide embeddings.

---

## 📁 Project Structure

```bash
gmfc101/
├── core/              # Main source code for processing API calls
├── data/samples/      # Small sample transcript files (JSON)
├── data/metadata.json # Listing of all available transcripts (JSON)
├── prompts/           # Prompts used for workflow and answering user query
├── .env.example       # Example env file for setup
├── .api.py            # Main API endpoint
├── README.md
├── LICENSE
└── ...
```

## 🚀 Getting Started

1. **Clone the repo**

   ```bash
   git clone https://github.com/atenger/gmfc101.git
   cd gmfc101
   ```

2. **Create and activate virtual environment**

   ```powershell
   # Create virtual environment
   python -m venv venv

   # Activate virtual environment
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Create `.env` file**
   Copy `.env.example` and fill in your keys:

   ```bash
   cp .env.example .env
   ```

5. **Download transcripts**
   Run the script to populate the transcript database:

   ```bash
   python scripts/download_transcripts.py
   ```

6. **Run the app locally**

   ```bash
   python api.py
   ```

7. **Call the API to test it**

   ```
   Call test_webhook API with cast_url in the request

      {
       "cast_url": "https://warpcast.com/jc4p/0xc8a8bcbe"
      }
   ```

---

## 🧪 Transcript Data Format

Each transcript file is a `.json` file.
Refer to samples for formatting.  
Deepgram was used to generate the files based on YouTube videos.

---

## ⚙️ Environment Variables

| Variable                 | Description                                                                               |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY`         | Your OpenAI API key                                                                       |
| `PINECONE_API_KEY`       | Your Pinecone API key                                                                     |
| `PINECONE_ENVIRONMENT`   | Your Pinecone environment                                                                 |
| `PINECONE_INDEX_NAME`    | Your Pinecone index name                                                                  |
| `NEYNAR_API_KEY`         | Your Neynar API key                                                                       |
| `NEYNAR_BOT_SIGNER_UUID` | Your Neynar signer UUID key                                                               |
| `USE_LLM`                | Set to true                                                                               |
| `DRY_RUN_SIMULATION`     | Set to true when testing to avoid creating casts                                          |
| `DATA_DIR`               | Path to your local data directory (default: `./data`)                                     |
| `BOT_ACCOUNT_FID`        | Your bot's FID, used to avoid responding to itself                                        |
| `USE_SAMPLES`            | Whether to use sample files or to downloa dthe full set of production transcripts from S3 |
| `VERBOSE_LOGGING`        | Set to false except when debugging                                                        |
| `AWS_ACCESS_KEY_ID`      | Your AWS Access key                                                                       |
| `AWS_SECRET_ACCESS_KEY`  | Your AWS Secret Access key                                                                |
| `S3_BUCKET`              | Name of your AWS bucket that contains transcripts                                         |

---

## 🤝 Contributing

We welcome contributions! You can:

- Build out test cases
- Improve the bot's conversational abilities and ability to feel more human like in the Farcaster feed
- Submit bug fixes or features

Please use the sample transcripts for development and testing. If you build something cool, let us know!

---

## 📜 License

Copyright 2025 GM Farcaster Network LLC

This project is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).  
You are free to use, modify, and distribute this software with proper attribution.

---

Made with ❤️ by the GM Farcaster team.
