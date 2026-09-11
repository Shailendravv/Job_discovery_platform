# Running Two GitHub Accounts on One Machine

Setup notes for using a **work** GitHub account and a **personal** GitHub account
side by side on the same Windows machine, without them stepping on each other.

## Accounts

| Role     | Email                              | GitHub username example |
|----------|-------------------------------------|--------------------------|
| Work     | shailendra.c@shyenatechyarns.in     | Shailendra2011           |
| Personal | shailendramiet2@gmail.com           | Shailendravv             |

## 1. SSH keys (one per account)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_github_work -N "" -C "github-work"
ssh-keygen -t ed25519 -f ~/.ssh/id_github_personal -N "" -C "github-personal"
```

Add each **public** key to the matching GitHub account under
**Settings → SSH and GPG keys → New SSH key**. A key can only be registered
to one account — that's what makes the split work.

```bash
cat ~/.ssh/id_github_work.pub       # → paste into the WORK account
cat ~/.ssh/id_github_personal.pub   # → paste into the PERSONAL account
```

## 2. SSH config aliases

`~/.ssh/config`:

```
Host github-work
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_github_work
    IdentitiesOnly yes

Host github-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_github_personal
    IdentitiesOnly yes
```

The alias you use in the **remote URL** picks which key (and therefore which
account) authenticates:

```bash
git clone git@github-work:some-org/some-repo.git
git clone git@github-personal:your-username/some-repo.git
```

Verify each alias resolves to a different account:

```bash
ssh -T git@github-work
ssh -T git@github-personal
```

Each should print `Hi <username>! You've successfully authenticated...`
with a **different** username.

## 3. Commit identity (name/email) per account

Global default (`~/.gitconfig`) — used everywhere except the personal folder below:

```
[user]
    email = shailendra.c@shyenatechyarns.in
    name = Shailendra
```

Personal override — `~/.gitconfig-personal`:

```
[user]
    name = Shailendra
    email = shailendramiet2@gmail.com
```

Auto-switch by folder — add to `~/.gitconfig`:

```
[includeIf "gitdir:C:/Users/shail/personal/"]
    path = C:/Users/shail/.gitconfig-personal
```

Any repo cloned under `~/personal/` automatically commits with the personal
email; everything else uses the work identity. Keep this folder discipline,
or set `user.name`/`user.email` manually per repo if a repo lives elsewhere.

## 4. Putting it together for a repo

```bash
cd ~/personal
git clone git@github-personal:Shailendravv/Job_discovery_platform.git
cd Job_discovery_platform
git config user.name          # -> Shailendra          (from includeIf)
git config user.email         # -> shailendramiet2@gmail.com
git push                      # authenticates via id_github_personal
```

For an existing repo that already has an HTTPS remote, switch it to SSH:

```bash
git remote set-url origin git@github-personal:Shailendravv/Job_discovery_platform.git
git config user.name  "Shailendra"
git config user.email "shailendramiet2@gmail.com"
```

## 5. Troubleshooting: `403 ... denied to <other-account>`

```
remote: Permission to Shailendravv/Job_discovery_platform.git denied to Shailendra2011.
fatal: unable to access 'https://github.com/Shailendravv/Job_discovery_platform.git/': The requested URL returned error: 403
```

**Cause:** the repo used an `https://github.com/...` remote. HTTPS auth relies
on a single cached credential (Windows Credential Manager / Git Credential
Manager) for `github.com`, shared across *all* repos regardless of folder or
`git config user.email`. If that cache holds the work account's token, every
HTTPS push authenticates as the work account — even against a repo owned by
the personal account. This is a **credential** problem, not an email/identity
problem.

**Fix:** switch the remote to SSH using the correct alias (step 4 above) so
each repo explicitly picks its own key instead of relying on a shared cache.

**Alternative fix (stay on HTTPS):** clear the cached credential —
Control Panel → Credential Manager → Windows Credentials → remove the
`git:https://github.com` entry — then re-authenticate as the correct account
next push. This resets the *shared* cache, so it only fixes one repo at a
time and will keep colliding as you switch between accounts. SSH aliases
avoid this entirely.

## 6. Alternative: staying on HTTPS (no SSH keys)

If you'd rather not manage SSH keys, you can keep every remote on `https://`
and still avoid the collision in section 5 — as long as **every** remote URL
embeds its account's username. Git Credential Manager (`credential.helper =
manager`, already the global setting on this machine) keys its cached
credential by `protocol + host + username`. Leave the username off and
everything falls back to one shared entry (`git:https://github.com`) that the
next account to authenticate silently overwrites — that's the exact 403
scenario in section 5. Put a username on **every** remote, work and personal
alike, and each account gets its own entry instead of fighting over the
shared one.

```bash
# Personal repo
git remote set-url origin https://Shailendravv@github.com/Shailendravv/Job_discovery_platform.git

# Work repo
git remote set-url origin https://Shailendra2011@github.com/some-org/some-repo.git
```

First push/fetch after changing the URL, GCM won't have a cached entry for
that exact `user@host` key yet, so it opens a fresh sign-in prompt (browser
or device code) — sign in as the matching account and it's cached from then
on. Verify which account is cached for a given URL any time with:

```bash
cmdkey /list | findstr /C:"github.com"
```

You should see one `LegacyGeneric:target=git:https://<username>@github.com`
entry per account, each with a matching `User:` line — never both accounts
sharing the bare `git:https://github.com` target.

This repo's `origin` has already been switched to the personal, username-
qualified URL above. Commit identity (`user.name`/`user.email`) is separate
from this and still follows section 3 — it wasn't changed here.

## Quick reference

| Need | Command |
|---|---|
| Clone as work | `git clone git@github-work:ORG/REPO.git` |
| Clone as personal | `git clone git@github-personal:USER/REPO.git` |
| Switch existing remote | `git remote set-url origin git@github-<alias>:OWNER/REPO.git` |
| Check which account a repo uses | `git remote -v` (look at the alias) |
| Check commit identity | `git config user.name && git config user.email` |
| Test SSH auth | `ssh -T git@github-work` / `ssh -T git@github-personal` |
| Switch remote to HTTPS (per account) | `git remote set-url origin https://<username>@github.com/OWNER/REPO.git` |
| Check cached HTTPS creds | `cmdkey /list \| findstr /C:"github.com"` |
