# KnowYourMPZA Frontend

Public V1 website for browsing source-backed South African MP data.

## Run Locally

```bash
npm install
npm run dev
```

Set the backend URL if it is not `http://localhost:8000`:

```bash
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

## Build

```bash
npm run build
```

## Scope

The frontend shows MPs, parties, committees, PMG evidence, parliamentary questions, source links, and quality data. It does not include authentication, payments, AI summaries, chat, bills, or voting records.
