# Deploy Jowar

The backend runs on AWS (region ap-south-1, Mumbai). The page is static files served by Vercel.
Do these in order. Nothing here needs an access key in your code or in chat.

## 0. Safety first
1. Billing > Budgets: create a budget with an alert at about Rs 100. Turn on Free Tier usage alerts in Billing preferences.
2. MFA on the root login and on any IAM user you use. Do not create access keys; this project needs none.
3. Keep `.gitignore` in the repo folder.

## 1. DynamoDB table
- Name `rainwatch`, partition key `pk` (String), sort key `sk` (String), on-demand capacity.

## 2. Lambda
- Create function `rainwatch`, runtime Python 3.12. Do NOT create a Function URL for it (it would bypass the API limits below).
- Upload a zip with these files at the top level: run `python make_zip.py` and upload `jowar-lambda.zip`.
- Configuration > Environment variables: `TABLE_NAME` = `rainwatch`. Timeout 15 s, memory 256 MB.
- Role permissions (least privilege): replace ACCOUNT_ID with yours and attach as an inline policy:
```json
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["dynamodb:GetItem","dynamodb:PutItem"],
 "Resource":"arn:aws:dynamodb:ap-south-1:ACCOUNT_ID:table/rainwatch"}]}
```
- Optional cap on parallel runs: Configuration > Concurrency > Reserved concurrency 5. New accounts often cannot set this; if AWS refuses, skip it.

## 3. API Gateway (HTTP API) and cost limits
- Create an HTTP API with a Lambda integration to `rainwatch`, one route `ANY /{proxy+}`, stage `$default` with auto-deploy.
- Stage > Throttling: default route throttling rate 5, burst 10, so nobody can run up your bill.
- Do not turn on access logging: the privacy policy says it is off. Leave API Gateway CORS off; the Lambda sets it.
- Test in a browser: `INVOKE_URL/corridors` lists 8 areas and `INVOKE_URL/replays` lists 2 events.
- CloudWatch > Log groups > /aws/lambda/rainwatch > Actions > Edit retention setting: 14 days.

## 4. EventBridge schedule
- EventBridge > Schedules > Create schedule: rate 30 minutes, target Lambda `rainwatch`, payload `{"task": "refresh"}`.

## 5. The page on Vercel
1. Put the repo on GitHub (public).
2. `index.html`: `API_BASE` is your Invoke URL. In `vercel.json` the `connect-src` entry must be the same address. If you change one, change the other.
3. vercel.com > Add New > Project > import the repo. Framework preset: Other. Leave the build command and output directory empty. Deploy.
4. Do not enable Vercel Analytics or Speed Insights: the privacy policy says there are none.
5. Open the https address in a private window. Footer links must open the privacy policy and terms.

## 6. Lock the API to your page (recommended, after step 5)
- Lambda > Configuration > Environment variables: add `ALLOWED_ORIGIN` = your Vercel address exactly, for example `https://jowar.vercel.app` (https, no slash, no path). Save.
- Reload the page and run a check. If you see "Failed to fetch", the value does not match the address in the browser bar: fix it or delete the variable.
- This stops other websites from calling the API from their pages. It does not stop scripts, which is why the throttling in step 3 matters.

## 7. Check it really works
- Live tab: Behala, today, an hour. A result with a day strip appears. DynamoDB item `forecast / behala` exists.
- Replay tab: each event shows its note.
- Feedback: pick an hour that has already started, tap Yes. A `feedback#behala` item appears with only depart, level and flooded.
- CloudWatch Logs show your requests. After the next 30-minute mark `fetched_at` in DynamoDB changes.

## 8. Video (under 3 min)
Live URL in a private window, a live check, a replay with its note, then the AWS console: Lambda, DynamoDB items, EventBridge schedule, CloudWatch logs. Say that Vercel only serves the page and the rest runs on AWS. Blur your account ID.
