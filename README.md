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

This is currently a process-local domain store, not durable storage and not connected to CSV loading or an API. The profile ID is an identifier, not an authorization token. The API layer still needs authentication, durable storage, and encryption for transaction history before this can hold end-user data.

