# Tests

Run with:

```bash
python -m pytest
```

Pushover notification reliability tests include:
- DNS is re-resolved on every retry attempt.
- DNS resolution failures raise the DNS-specific error path.
- Retry backoff schedule is `2s`, then `5s`.
