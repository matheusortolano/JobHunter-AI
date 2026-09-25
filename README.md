# JobHunter AI

Cloud-based job discovery and filtering system built with Python and AWS.

The project automatically collects job opportunities from multiple public sources, normalizes and deduplicates the results, applies eligibility and scoring rules, stores execution data in AWS S3 and delivers selected opportunities through Telegram.

The current cloud version runs on AWS Lambda and can be scheduled automatically using Amazon EventBridge Scheduler.

---

## Overview

Job searching across multiple platforms can become repetitive and difficult to organize.

JobHunter was created as a personal automation project to centralize this process.

The application:

- collects job opportunities from multiple sources;
- normalizes data from different APIs;
- removes duplicate vacancies;
- evaluates location and work-model eligibility;
- calculates relevance scores;
- separates eligible, uncertain and ineligible opportunities;
- stores execution state and results;
- prevents previously delivered vacancies from being repeatedly shown;
- sends selected opportunities to Telegram.

---

## Architecture

```text
Arbeitnow
Remote OK
Adzuna
    │
    ▼
Job collection
    │
    ▼
Normalization
    │
    ▼
Deduplication
    │
    ▼
Eligibility filters
    │
    ▼
Scoring and classification
    │
    ▼
AWS Lambda
    │
    ├── AWS S3
    │     ├── execution snapshots
    │     ├── latest results
    │     └── seen jobs state
    │
    ├── AWS Systems Manager
    │     └── credentials / parameters
    │
    └── Telegram Bot API
          └── selected job notifications

Amazon EventBridge Scheduler
            │
            ▼
       AWS Lambda