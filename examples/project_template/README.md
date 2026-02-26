# Project Template Cloning Example

Demonstrates using django-graph-walker to duplicate a project template for a new user — a common pattern in apps where users get their own copy of a shared template (onboarding checklists, starter projects, etc.).

## The model

```
Project (owner, is_template)
  └─ Section (title, order)
       └─ Task (title, description, order)
            └─ Tag (M2M, shared — not cloned)
```

## Setup

```bash
pip install -r requirements.txt
pip install -e ../../  # install django-graph-walker from source
python manage.py migrate
python scripts/setup_data.py
```

## Clone a project for a user

```bash
python scripts/clone_for_user.py
```

This will:
1. Walk the template project, collecting all its sections and tasks
2. Clone everything with new PKs, remapping all FKs
3. Reassign ownership to the target user
4. Keep shared tags as-is (they're out of scope, so references are preserved without duplication)

## How it works

The key is the `GraphSpec` — it declares what to clone and what to leave alone:

```python
spec = GraphSpec({
    Project: {
        "owner": Override(lambda inst, ctx: ctx["user"]),  # reassign
        "is_template": Override(False),                     # no longer a template
    },
    Section: {},  # clone as-is
    Task: {},     # clone as-is, tags are out of scope so kept automatically
})
```

Tag is **not** in the spec, so it's out of scope. The walker won't traverse to tags, and the cloner will preserve the original M2M references — every cloned task points to the same shared tags as the original.
