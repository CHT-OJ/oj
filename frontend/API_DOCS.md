# Django API v2 Documentation

This document outlines the available API endpoints provided by the Django backend. All endpoints are prefixed with `/api/v2/`.

---

## 1. Contests

### GET `/api/v2/contests`

Retrieves a paginated list of visible contests.

**Query Parameters:**
- `is_rated` (boolean): Filter contests by whether they are rated.
- `key` (string, multiple): Filter contests by a list of keys (e.g., `?key=contest1&key=contest2`).
- `tag` (string, multiple): Filter contests by a list of tags.
- `organization` (integer, multiple): Filter contests by a list of organization IDs.

**Example Response:**
```json
{
  "api_version": "2.0",
  "method": "get",
  "fetched": "...",
  "data": {
    "current_object_count": 1,
    "objects_per_page": 50,
    "page_index": 1,
    "has_more": false,
    "objects": [
      {
        "key": "contest_key",
        "name": "Contest Name",
        "start_time": "...",
        "end_time": "...",
        "time_limit": 10800.0,
        "is_rated": true,
        "rate_all": false,
        "tags": ["tag1", "tag2"]
      }
    ]
  }
}
```

### GET `/api/v2/contest/<contest_key>`

Retrieves detailed information about a single contest.

**URL Parameters:**
- `contest_key` (string): The unique key of the contest.

**Example Response:**
```json
{
  "api_version": "2.0",
  "method": "get",
  "fetched": "...",
  "data": {
    "object": {
      "key": "contest_key",
      "name": "Contest Name",
      "start_time": "...",
      "end_time": "...",
      // ... other contest details ...
      "problems": [
        {
          "points": 100,
          "code": "PROBLEM_CODE",
          "name": "Problem Name"
        }
      ],
      "rankings": [
        {
          "user": "username",
          "score": 100,
          "cumulative_time": "..."
        }
      ]
    }
  }
}
```

---

## 2. Problems

### GET `/api/v2/problems`

Retrieves a paginated list of visible problems.

**Query Parameters:**
- `partial` (boolean): Filter problems by whether they allow partial scores.
- `code` (string, multiple): Filter by a list of problem codes.
- `group` (string, multiple): Filter by a list of problem groups (e.g., `?group=Ad-Hoc`).
- `type` (string, multiple): Filter by a list of problem types.
- `organization` (integer, multiple): Filter by a list of organization IDs.
- `search` (string): Perform a full-text search on problems.

### GET `/api/v2/problem/<problem_code>`

Retrieves detailed information about a single problem.

**URL Parameters:**
- `problem_code` (string): The unique code of the problem.

---

## 3. Users

### GET `/api/v2/users`

Retrieves a paginated list of users.

**Query Parameters:**
- `id` (integer, multiple): Filter by a list of user IDs.
- `username` (string, multiple): Filter by a list of usernames.
- `organization` (integer, multiple): Filter by a list of organization IDs the users belong to.

### GET `/api/v2/user/<username>`

Retrieves detailed information about a single user.

**URL Parameters:**
- `username` (string): The username of the user.

**Example Response:**
```json
{
  // ...
  "data": {
    "object": {
      "id": 1,
      "username": "user1",
      "points": 123.45,
      "solved_problems": ["problem1", "problem2"],
      "rating": 1500,
      "contests": [
        {
          "key": "contest_key",
          "score": 100,
          "rating": 1550
        }
      ]
    }
  }
}
```

---

## 4. Submissions

### GET `/api/v2/submissions`

Retrieves a paginated list of submissions.

**Query Parameters:**
- `user` (string): Filter by username.
- `problem` (string): Filter by problem code.
- `id` (integer, multiple): Filter by a list of submission IDs.
- `language` (string, multiple): Filter by a list of language keys (e.g., `?language=cpp17&language=py3`).
- `result` (string, multiple): Filter by a list of result codes (e.g., `?result=AC&result=WA`).

### GET `/api/v2/submission/<submission_id>`

Retrieves detailed information about a single submission. **Requires login.**

**URL Parameters:**
- `submission_id` (integer): The ID of the submission.

**Example Response:**
```json
{
  // ...
  "data": {
    "object": {
      "id": 12345,
      "problem": "PROBLEM_CODE",
      "user": "username",
      "language": "cpp17",
      "result": "AC",
      "cases": [
        {
          "case_id": 1,
          "status": "AC",
          "time": 0.1,
          "memory": 1024
        }
      ]
    }
  }
}
```

---

## 5. Other Endpoints

### GET `/api/v2/organizations`

Retrieves a list of organizations.
- **Query Params**: `is_open` (boolean), `id` (integer, multiple).

### GET `/api/v2/participations`

Retrieves a list of contest participations.
- **Query Params**: `contest` (string), `user` (string), `is_disqualified` (boolean).

### GET `/api/v2/languages`

Retrieves a list of available programming languages.

### GET `/api/v2/judges`

Retrieves a list of online judge servers.
