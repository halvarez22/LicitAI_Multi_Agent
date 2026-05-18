import json
import redis
import sys
import os

# Add the backend to sys.path to import settings
sys.path.append(os.getcwd())

try:
    from app.config.settings import settings
    
    redis_client = redis.Redis(
        host=settings.REDIS_HOST, 
        port=settings.REDIS_PORT, 
        decode_responses=True
    )

    keys = redis_client.keys("job:*")
    print(f"Total Jobs in Redis: {len(keys)}")
    for key in keys:
        job_data = redis_client.get(key)
        if job_data:
            job = json.loads(job_data)
            print(f" - ID: {job.get('job_id')} | Status: {job.get('status')} | Updated: {job.get('updated_at')}")
except Exception as e:
    print(f"Error connecting to Redis: {e}")
