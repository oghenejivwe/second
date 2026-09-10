# What I need from you

**Everything on this list is something only you can do** — it needs your
identity, your card, or a decision that is yours. Nothing else is blocked on you.

Ordered by what unblocks the most. Roughly **3 hours** of console work, plus five
answers that take two minutes.

> **Timezone is no longer on this list.** Second reads it from your Google
> Calendar, which is where it actually lives and which follows you when you
> travel. Falls back to this machine, then to UTC, and records which -- so an
> agent can decline to be precise about times it guessed rather than quietly
> being an hour out.

---

## A. Five answers I need (2 minutes, no console)

Reply to these in chat. Three of them change what I build.

| # | Question | Why it matters |
|---|---|---|
| A1 | **Do you already have an AWS account, or starting from zero?** | Changes the whole setup path and whether there is billing history. |
| A2 | **Is `jivwewonder@gmail.com` consumer Gmail or Workspace?** Does `admin.google.com` open? | Workspace can skip the consent-screen dance entirely via domain-wide delegation, and handles inserted mail differently. |
| A4 | **Your three real goals for the demo** — or shall I invent them? | Real goals make a far better demo than invented ones, and the Route Planner's rationale reads as genuine. |
| A5 | **Tavily or Brave** for web search? | Only affects one dependency. Tavily is the cheapest to obtain. |
| A6 | **GitHub repo — shall I create it with `gh`, or will you?** | Public repo with MIT visible is a submission requirement. If `gh` is already authenticated here, I can do it. |

---

## B. AWS — do these in this order

### B1. Credits and billing · ~10 min · **DO THIS FIRST**

This is a one-way door and it is the single highest-impact unknown in the build.

1. Billing and Cost Management → confirm a **valid payment method** exists.
   Required for AWS Marketplace regardless of credits.
2. Credits → redeem the hackathon code.
3. **Read the "Applicable products" column on the credit.**

**Why this is first:** Anthropic models on Bedrock bill through **AWS
Marketplace** under the model provider, not under the Bedrock service line, and
AWS promotional credits have historically **excluded Marketplace**. If they are
excluded you are spending real money from the first token, which changes the
model choice, the iteration budget, and whether I keep the scripted model as the
default dev path. **If it excludes Marketplace, ask the organisers whether the
credits are Bedrock-scoped before we build further.**

### B2. Credentials · ~30 min

There is no `~/.aws` on this machine at all — no credentials, no region.

Use **IAM Identity Center**, not a long-lived access key. Same setup time, no
secret on disk, and this repo becomes public during a hackathon.

1. IAM Identity Center → Enable, identity store region **us-west-2**
2. Users → add yourself
3. Permission sets → Create → Custom → attach `deploy/iam-policy.json`
   (I have written it; it is in this repo). Session duration 8 hours.
4. AWS accounts → assign yourself + that permission set
5. Copy the **AWS access portal URL** from the Identity Center dashboard
6. Run:
   ```
   aws configure sso
   ```
   Session name `second`, that start URL, SSO region `us-west-2`, CLI region
   `us-west-2`, output `json`, profile name `second`.
7. ```
   setx AWS_PROFILE second
   setx AWS_REGION us-west-2
   ```
   **Takes effect in NEW terminals only.**
8. Verify: `aws sts get-caller-identity --profile second`

Expect to re-run `aws sso login --profile second` roughly daily. **Do not debug
an expired SSO token as a code bug** — it is the single most common wasted hour.

### B3. Bedrock model access · ~15 min

**Not a queue.** Access is granted on submit, with up to 15 minutes for the
subscription to finalise. The spec was wrong about approval latency.

1. Region picker → **US West (Oregon) us-west-2**
2. Bedrock → Model catalog → filter Anthropic → **Claude Sonnet 4.6**
3. The console prompts for use-case details → Submit.
   A GitHub profile URL is explicitly acceptable for the company-website field.
4. Wait up to 15 min, then tell me and I will verify it from boto3.

### B4. Budget tripwire · ~5 min

Billing → Budgets → Cost budget → Monthly → **$50** → alerts at 50%, 80%, 100%
actual and 100% forecast → your email.

Understand what this is not: budgets only **alert**, and they lag 8–24 hours. The
real spend cap is the per-invocation token limit I have already wired in.

### B5. AWS CLI upgrade · ~5 min · optional

Installed is **2.7.24**. AgentCore subcommands need **≥ 2.27.42**. I can drive
everything from boto3 instead, so this is convenience, not a blocker.

### B6. AWS Builder ID · ~5 min

Required for the hackathon submission itself. Separate from your AWS account.

---

## C. Google — order matters more than anywhere else

### C1. Project and APIs · ~10 min

1. New project `second-agent`. On a personal Gmail this means **No organization**,
   and the "Internal" audience option will be greyed out. That is expected.
2. Enable **Google Calendar API** and **Gmail API**.

### C2. Auth Platform · ~10 min

1. `console.cloud.google.com/auth/branding` → Get started → App Information →
   Audience **External** → Contact → agree to the User Data Policy → Create
2. `auth/scopes` → Add or remove scopes → add **all five**:
   - `https://www.googleapis.com/auth/calendar`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.compose`
   - `https://www.googleapis.com/auth/gmail.insert` ← seeder
   - `https://www.googleapis.com/auth/calendar.events` ← seeder

   **All five go on the one app.** Scope registration is app-level; each OAuth
   client then requests a subset. Register only three and the seeder's consent
   screen fails — and you would find that out on the 13th, seeding the demo.
   Both seeder scopes are Restricted, exactly like the two already there, so this
   adds no verification exposure. Sixty seconds now.
3. **Ignore the verification nag. Never click "Submit for verification."**
   Both Gmail scopes are Restricted, and verification is a CASA assessment that
   takes weeks. We do not need it.
4. `auth/audience` → Test users → add `jivwewonder@gmail.com`

### C3. ⚠️ PUBLISH THE APP — before anything else touches it · ~2 min

`auth/audience` → **PUBLISH APP** → confirm. Status flips *Testing* → *In
production*.

**This is the step that saves the demo, and it cannot be done retroactively.**

A refresh token minted while the app is in *Testing* **expires in 7 days, and the
fuse is set at the moment it is issued.** Publishing afterwards does not defuse a
token that already exists. Adding yourself as a test user does not exempt you —
the rule keys on publishing status, not on who you are.

A build submitted on the 14th and judged a week later dies with a
`400 invalid_grant` that looks exactly like a code bug, at the worst possible
moment.

Publishing takes one click, needs no verification, and works for up to 100 users.

### C4. Two OAuth clients · ~10 min

`auth/clients` → Create client → Application type **Desktop app**, twice.

| Client | Scopes | Save as | Shipped? |
|---|---|---|---|
| **runtime** | calendar, gmail.readonly, gmail.compose | `client_secret.json` | yes |
| **seeder** | gmail.insert, calendar.events | `client_secret_seed.json` | **never** |

Both are gitignored already.

**Why two.** `users.messages.insert` — the only way to place a backdated email —
accepts only `mail.google.com`, `gmail.modify` or `gmail.insert`. The runtime
scopes genuinely cannot seed the demo inbox. Splitting them costs nothing and it
**proves the agent cannot fabricate the evidence it later cites**, which is a
better story than the alternative.

Put both JSON files in the repo root. **Do not paste their contents to me** — I
never need to see a credential, only that the file exists.

---

## D. One key

**Web search API key** — Tavily (`tavily.com`) or Brave. Put it in `.env` as
`TAVILY_API_KEY=` or `BRAVE_API_KEY=`. I have written `.env.example`.

Lowest priority on this page: the Resource Finder that uses it is first on the
project's cut list.

---

## What happens when each lands

| You finish | I can then |
|---|---|
| A1–A6 | finalise the demo scenario and the Scheduler's timezone handling |
| B1 | decide whether live Bedrock is the dev default or scripted stays |
| B2 | create the DynamoDB table and S3 bucket, verify model access |
| B3 | run the first real Bedrock call and confirm structured output on a live model |
| B2 + B3 | **attempt the AgentCore deploy — the highest-duration risk in the plan** |
| C1–C4 | CONNECTORS can authorise, then seed the demo account |
| D | the Resource Finder becomes buildable |

**The AgentCore deploy is the one with a clock on it.** It runs CDK and needs the
account bootstrapped, which needs broad IAM to assume the bootstrap roles. On a
fresh account with a scoped-down identity that is the most likely hard stop in
the whole build, and it wants discovering on day 1 against a hello-world — not on
day 3 against the real agent.
