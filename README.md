# 48toNone Backend

This is the backend for our project for the Veritas AI hackathon.
The Veritas AI hackathon is a 48 hour hackathon for highschoolers worldwide. 
Currently very much in production and readme will get more detail as hackathon goes on. 

Link to Veritas Competition Website:
https://highschoolhackathon.org/

Team Name:
48toNone

Var naming convention guide:

Data prefix:
D_func
D_object

Common prefix:
C_func

## Account profiles (domain model)

`src/profiles.py` defines the profile/account/tag ownership model for the future API. A profile has a generated `profile_id` and is uniquely associated with an authenticated `owner_id`; creating one also creates a stable-ID `General` default tag. Each account belongs to exactly one tag and owns its own baseline and imported sheet references. Accounts can be moved between tags without moving their history or baseline; deleting a custom tag moves its accounts to `General`.

`src/profiles.py` contains the domain rules. `src/profile_repository.py` provides
DynamoDB persistence for the initial profile API operations. Configure a
DynamoDB table with string partition key `owner_id` and string sort key
`record_key`, then set `PROFILE_TABLE_NAME` for the runtime. The table layout
reserves separate owner-scoped records for the profile, tags, and accounts. The
current repository writes the profile and its default `General` tag in one
conditional transaction, preventing duplicate profiles for an owner;
persistence methods for custom tags and accounts still need to be added.
For an API Gateway HTTP API Lambda integration, use `src.profile_handler.handler`
as the Lambda handler; `make_handler(repository)` remains injectable for local
tests and other runtimes.

Build a Lambda deployment ZIP with only the profile modules and AWS SDK
dependency (without the large fraud-model dependencies):

```powershell
python scripts/package_profile_lambda.py
```

The artifact is written to `dist/profile-lambda.zip`. Configure the Lambda
runtime as Python 3.14, the handler as `src.profile_handler.handler`, and set
`PROFILE_TABLE_NAME` to the DynamoDB table name.

The profile ID is an identifier, not an authorization token. The API handler
must receive the owner ID from an authenticated request context. The current
profile API work does not persist transaction histories; those require a
separate storage and encryption design.

## Profile API routes (AWS Lambda)

All routes need a Cognito sign-in token and only ever touch the signed-in user's own records.

| Route | What it does |
|---|---|
| `POST /profiles` | Create the profile and its `General` tag |
| `GET /profiles/me` | The profile with its tags and accounts |
| `POST /profiles/me/tags` `{name}` | Create a tag |
| `PATCH /profiles/me/tags/{tag_id}` `{name}` | Rename a tag |
| `DELETE /profiles/me/tags/{tag_id}` | Delete a tag; its accounts move to `General` |
| `POST /profiles/me/accounts` `{name, tag_id?}` | Create an account (in `General` unless a tag is given) |
| `PATCH /profiles/me/accounts/{account_id}` `{name?, tag_id?}` | Rename an account and/or move it to another tag |
| `DELETE /profiles/me/accounts/{account_id}` | Delete an account |

## Local dashboard API

`src/api.py` runs the whole program (startup, model, fraud check, refresh) and serves the results
as JSON for the frontend dashboard. It also stores the CSVs users upload to their accounts:

```
.venv/bin/python -m src.api          # http://127.0.0.1:8000
```

| Route | What it does |
|---|---|
| `GET /report?profile=<profile_id>` | The fraud report for one profile's uploaded CSVs |
| `PUT /sheets/<profile_id>/<account_id>/<name>.csv` | Upload a CSV to an account (the body is the file) |
| `DELETE /sheets/<profile_id>/<account_id>/<name>.csv` | Delete one CSV |
| `DELETE /sheets/<profile_id>/<account_id>` | Delete every CSV of an account |

Uploads are kept in `user_data/` (git-ignored) and are checked as soon as they arrive. The server
only listens on this machine and trusts its caller: the frontend server checks who is signed in
before calling it. The model is too large for the profile Lambda, so the fraud check runs locally.
Each CSV is analysed on its own; accounts in the same tag do not share a baseline yet.

Each purchase in the report has one status: `fraud` (the model flagged that purchase), `suspicious`
(it is part of a pattern of charges from one seller that keep getting more frequent, and the model
says to take a look), `cleared` (it looked irregular and the model passed it) or `ok`. The pattern
check is `patterns()` in `src/datasheet.py`; the model's question for it is `review_patterns()` in
`src/model.py`. `sample_uploads/` has two made-up statements that show it: one where the small charges rise
steadily and one where they rise unevenly, with quiet weeks and busy days.
