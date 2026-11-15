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

The profile ID is an identifier, not an authorization token. The API handler
must receive the owner ID from an authenticated request context. The current
profile API work does not persist transaction histories; those require a
separate storage and encryption design.

