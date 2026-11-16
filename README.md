# How to run the full thing locally (two terminals):
    backend repo:   .venv/bin/python -m src.api     -> http://127.0.0.1:8000
    frontend repo:  npm run dev                     -> http://localhost:3000
    The frontend needs a .env.local, fill it in.


Terminal 1: backend (repo root, the folder with src/)

cd "path\to\48-to-none-backend"
.venv\Scripts\Activate.ps1
python -m src.api

Check http://127.0.0.1:8000/health.

Terminal 2: frontend (repo root, the folder with package.json)

cd "path\to\48-to-none-frontend"
npm install
npm run dev

Then open http://localhost:3000.

.env.local must exist next to package.json before npm run dev:

PROFILE_API_URL=https://hraukl7w0g.execute-api.us-east-2.amazonaws.com
FRAUD_API_URL=http://127.0.0.1:8000
COGNITO_REGION=us-east-2
COGNITO_CLIENT_ID=3d8f11uocqbc1jnaj9puv8lj9t

npm install is only needed the first time, or after a git pull that changes package.json.

_____________________________________________________________________________________________
WRITE UP:

# L. U. C. K. I.

Track: Finance

**Team Name:** "48toNone"
**Team:** Juan Cruz Jr, Ivan Duong, and Matt J. A. Nozawa

## The problem: Transaction Security

Money is moving in an ever ephemeral direction. Gone are the days of things being worth their weight in gold. Now most people only need their phone to purchase whatever they desire or need. However, this poses the issue of transaction security. Digital money is easy to use, but that also means it’s just as easy to manipulate.

Bad actors can easily steal money from a digital wallet as easily as you pay for a bar of chocolate. Whether it’s from RFID skimming, data leaks, or simply bad opsec, your money could be taken from right under your nose and you wouldn’t be able to notice it right away. People less privy to technology are the biggest targets, and the majority of people. Think of your grandpa opening his checking account and seeing 0.99 withdrawals every other day for “Grandpa six withdrawal” or “Totally legit fridge company.” Even [apple.com/bill](http://apple.com/bill) is guilty of this. It’s impossible to analyze every account, bank statement, and transaction all at once by just looking at it.

## What we built

Our answer? Man’s best friend. Figuratively speaking, of course. A watchdog: an application that reviews your transactions and transaction history in order to key out potential risks and fraudulent behavior. Utilizing an AI model to give a comprehensive review and daemons to keep the watchdog working as intended.

> We’ve decided to dub this application “L. U. C. K. I.” for Lucid User Cost Knowledge Interface. Named after Juan’s dog “Lucki.”

## How it works

**Data:** We used a plethora of financial data. Our team members pulled some local data from their own financial histories as a starting point, then we added public data to test the model even further. Feeding our program and model synthetic data and then public data later on once we confirmed it was working as intended. The data became our personal baseline, and we later integrated a system for specific baselines. The model is pretrained, but each personal transaction baseline is calculated from that user's earlier transaction history.

We’ve designed Lucki to allow the user to keep track of their financial histories and transaction trends in an analytical manner. Most people have many different bank accounts, cards, and different use cases for their financial transactions. So we’ve compartmentalized our system to account for different transaction trends.

> Lucki infrastructure is built to show the end user concurrent predictions of fraud. Predicting fraud based on each tag’s baseline. Each tag is a different use case, the model develops its baseline off of the data inside the tag, regardless of the tag’s name.

**Model:** We used the Phi-4-mini model from Microsoft to act as our transaction analysis model.

## Results - Whole Group cross analysis

Our program filters data first, then sends suspicious or potentially fraudulent histories to our model. This program shortlists data points and does not send them to the model if it doesn’t detect suspicious data.

We evaluated Phi-4-mini-instruct on **31 held-out account targets** from Sparkov/FDB #4: 30 fraud targets and one clean control. Each account file contained 25 earlier transactions and one held-out target. Labels were kept in a separate file for scoring and were never shown to the model.

In the direct Phi test, we bypassed the heuristic shortlist and sent all 31 targets to Phi. Phi returned `OK` for all 31:

| Test | TP | FP | TN | FN | Accuracy | Precision | Recall | F1 | Specificity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Phi direct, shortlist bypassed | 0 | 0 | 1 | 30 | 3.23% | Undefined | 0% | 0% | 100% |

TP means a fraud target correctly flagged; FP means a clean target incorrectly flagged; TN means a clean target correctly left unflagged; FN means a fraud target missed. Accuracy is `(TP + TN) / 31`, or `1 / 31 = 3.23%`. Recall is `TP / (TP + FN)`, or `0 / 30 = 0%`. Precision is undefined because Phi made no fraud predictions (`TP + FP = 0`). F1 was reported as 0 when there were no positive predictions. Specificity is `TN / (TN + FP)`, or `1 / 1 = 100%`, but it is based on only one clean target and is not a reliable estimate.

In the end-to-end production pipeline, the heuristic shortlist sent **zero held-out targets** to Phi. The pipeline therefore scored TP=0, FP=0, TN=1, FN=30 (accuracy 3.23%, undefined precision, 0% recall, and 0% F1). This production score reflects the shortlist missing the fraud targets; it is not evidence that Phi reviewed and rejected them. The heuristic-only and Phi-in-production results are the same on this sample.

Phi was run in 4-bit NF4 with double quantization for the direct comparison. The sample is synthetic, heavily fraud-skewed, and has only one clean target, so these results do not establish real-world accuracy. More detail about the benchmark and data preparation is in [data/README.md](./data/README.md).

## What we'd do next

Given we had more time, connecting to a bank account would have been much more optimal rather than using a CSV. User usability would be much better with this. We would’ve also hosted a backend as well. This would’ve improved end user access. Another feature that might have been implemented would be bank linking. If we had more resources, we would make the AI model bigger and better. Lastly, having a minigame during failures would have been a nice addition to add.

## Sources - Ivan

Datasets, pretrained models, tutorials and AI tools used, with links.

**Generated Transaction Datasets:**

Conor. (2022). Simulated transactions. Kaggle.Com. [https://www.kaggle.com/datasets/conorsully1/simulated-transactions](https://www.kaggle.com/datasets/conorsully1/simulated-transactions)

**Fraud Datasets:**

Kartik2112. (n.d.). Fraud Detection. Kaggle. [https://www.kaggle.com/datasets/kartik2112/fraud-detection](https://www.kaggle.com/datasets/kartik2112/fraud-detection)

amazon-science. (2022). GitHub - amazon-science/fraud-dataset-benchmark: Repository for fraud dataset benchmark. GitHub. [https://github.com/amazon-science/fraud-dataset-benchmark](https://github.com/amazon-science/fraud-dataset-benchmark)

Kaggle. (2018). Credit Card Fraud Detection. Www.Kaggle.Com. [https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud)

**AWS Tutorial:**

Telusko. (n.d.). AWS tutorial for everyone in one shot [Video]. YouTube. Retrieved November 15, 2026. [https://youtu.be/KmsfUenqK4w](https://youtu.be/KmsfUenqK4w)

**Model References:**

[https://www.ibm.com/think/topics/ai-fraud-detection-in-banking](https://www.ibm.com/think/topics/ai-fraud-detection-in-banking)

**AI Usage:**

Statement from Juan:

> “When it comes to the code I personally was involved with, I used a mix of hand written code with ai support. For example I had AI help do severe stress testing of our project which helped find several critical bugs. I also had AI assist in getting a frontend set up really quickly. This means that most of the frontend design was done with AI in order to focus more on the backend and api.”

Statement from Ivan:

> “I used CodeX (AI) for providing detailed step by step guides on installations for AWS, Lambda, and DynamoDB. I also used CodeX for some assistance when installing the API.”

For checking debugs in the systems, I asked CodeX to run scans and tests on the system. During these debugs, It gave detailed responses, going in depth on informalities and certain issues that appeared during its scan of the system. Along with this, it listed a broad set of instructions on how we may counter and resolve the issues. When requested the AI would go more in depth of the solution. I used CodeX (Claude as well) for all of my code.

Statement from Matt:

> “I lead system design and development, mainly working as the systems engineer and mostly working on backend code. Adding features and implementing code, I spearheaded architecture and overall compatibility. Writing specific comments for where to insert unique code and how it should be specifically implements.
>
> In terms of AI usage, I wrote some framework code towards the beginning, allowing my agents to get a feel for how I like to code and comment. After I got them comfortable with my workflow, I switched to pure prompting. I specifically oversaw whatever my agents wrote. Most features in the backend are AI coded, but human ideas.; down to the minute architecture.
>
> Agent Clients I used include: Codex, Claude, Copilot, and Gemini.”
