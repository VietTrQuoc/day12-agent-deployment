# Deployment Information

## Public URL
https://project-lab-complete-production.up.railway.app

## Platform
Railway

## Test Commands

### Health Check
curl https://project-lab-complete-production.up.railway.app/health
# Expected: {"status":"ok"}

### Authentication Required
curl https://project-lab-complete-production.up.railway.app/ask
# Expected: 401 Unauthorized

### API Test (with authentication)
curl -X POST https://project-lab-complete-production.up.railway.app/ask \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question":"Hello"}'
# Expected: 200 OK

### Rate Limiting Test
for i in {1..15}; do \
  curl -X POST https://project-lab-complete-production.up.railway.app/ask \
    -H "X-API-Key: YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{"question":"test"}'; \
done
# Expected: eventually 429 Too Many Requests

## Environment Variables Set
- PORT
- REDIS_URL
- AGENT_API_KEY
- RATE_LIMIT_PER_MINUTE
- MONTHLY_BUDGET_USD
- ENVIRONMENT

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)


## Notes
- Keep .env.local out of git; only commit .env.example.
- `AGENT_API_KEY` is set as a Railway environment variable (not committed to repo).
