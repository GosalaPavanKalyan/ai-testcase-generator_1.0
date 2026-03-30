from flask import Flask, render_template, request, jsonify
import requests
import json
from google import genai
from google.genai import types

app = Flask(__name__)

# =============================
# CONFIGURATION
# =============================
PROJECT_ID = 10000

JIRA_AUTH = "Basic Z29zYWxhcGF2YW5rYWx5YW5AZ21haWwuY29tOkFUQVRUM3hGZkdGMFliLTdkaTg3ajZOSjhBLWdKS3FxbU0xXzNVNldRVW9HSHhsNEtMUVpSRXRzX2pjWVVMNFFqYkJIbzBSdVVfbUlrSVBHZ1hHUmRGd29iZV9CenNTV3c0dENROXpNQVhUbTJ4NkJWcmVsQXBqSzlBWHhBVTJGSW9LUmdOS2JULTJsc2RxVDZXZVpvWVE3QS1CdUlxTTlpeUtQaGRSYlFYRVJ5TjkwMnRySmxjWT03MkJGMUI5MA=="
AIO_AUTH = "AioAuth MzRlYmY2ZGUtNDMxNC0zZmJkLWFmYmItM2I4YWQ4Y2VlMGNhLjI2NTU1NjY1LWI4Y2ItNDkxNi05YTZmLWU0OWY5NjczNzFkYg=="
GEMINI_API_KEY = "AIzaSyCnbdNnDMSqusiCGIgz7JEvYLOfGTS0glI"

STATUS_PUBLISHED = 3


# =============================
# ADF TEXT EXTRACTOR
# =============================
def extract_text_from_adf(node):
    text = ""

    if isinstance(node, dict):
        if node.get("type") == "text":
            text += node.get("text", "")

        if "content" in node:
            for child in node["content"]:
                text += extract_text_from_adf(child)

        if node.get("type") in ["paragraph", "listItem"]:
            text += "\n"

    elif isinstance(node, list):
        for item in node:
            text += extract_text_from_adf(item)

    return text


# =============================
# GET JIRA TICKET
# =============================
def get_ticket_details(ticket_id):

    url = f"https://gosalapavankalyan.atlassian.net/rest/api/3/issue/{ticket_id}?fields=summary,description"

    headers = {
        "Authorization": JIRA_AUTH,
        "Accept": "application/json"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return None

    data = response.json()

    summary = data.get("fields", {}).get("summary")
    desc_obj = data.get("fields", {}).get("description")

    if not summary:
        return None

    description = extract_text_from_adf(desc_obj).strip() if desc_obj else ""

    return f"Summary: {summary}\n\nDescription:\n{description}"

# =============================
# GET EXISTING LINKED TEST CASES
# =============================
def get_existing_testcases(ticket_id):

    url = f"https://tcms.aiojiraapps.com/aio-tcms/api/v1/project/{PROJECT_ID}/traceability/requirement/{ticket_id}"

    headers = {
        "Authorization": AIO_AUTH,
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        return []

    data = response.json()

    cases = []

    for item in data:

        tc = item.get("testCase")

        if tc:
            cases.append({
                "title": tc.get("title"),
                "description": tc.get("description")
            })

    return cases


# =============================
# GENERATE TEST CASES
# =============================
def generate_test_cases(ticketdata, existing_cases):
    print("Generating Test Cases...", flush=True)

    client = genai.Client(api_key=GEMINI_API_KEY)

    SYSTEM_PROMPT = """
You are a Senior QA Automation Engineer.

Generate Positive, Negative, and Boundary test cases using data provided in <context> and skip the test cases that are already present in <existing_test_cases>.

<context>
{context}
</context>

<existing_test_cases>
{existing}
</existing_test_cases>

OUTPUT RULES
Return ONLY JSON array.

Each test case must contain:
- title
- description
- precondition
- steps (array of step strings)
"""

    formatted_prompt = SYSTEM_PROMPT.format(
        context=ticketdata,
        existing=json.dumps(existing_cases, indent=2)
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=formatted_prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json"
        )
    )

    try:
        return json.loads(response.text)
    except:
        return []


# =============================
# CREATE + LINK TEST CASE
# =============================
def create_and_link_testcase(ticket_id, test_case):

    create_url = f"https://tcms.aiojiraapps.com/aio-tcms/api/v1/project/{PROJECT_ID}/testcase"

    headers = {
        "Authorization": AIO_AUTH,
        "Content-Type": "application/json"
    }

    payload = {
    "title": test_case.get("title"),
    "description": test_case.get("description"),
    "precondition": test_case.get("precondition", ""),
    "scriptType": {
        "ID": 1
    },
    "status": {
        "ID": STATUS_PUBLISHED
    },
    "steps": [
        {
            "step": step,
            "data": "",
            "expectedResult": "",
            "stepType": "TEXT"
        }
        for step in test_case.get("steps", [])
    ]
}

    response = requests.post(create_url, headers=headers, json=payload)

    if response.status_code not in [200, 201]:
        return False

    testcase_id = response.json().get("ID")

    link_url = f"https://tcms.aiojiraapps.com/aio-tcms/api/v1/project/{PROJECT_ID}/testcase/{testcase_id}/detail"

    payload["jiraRequirementIDs"] = [ticket_id]

    requests.put(link_url, headers=headers, json=payload)
    print("CREATE STATUS:", response.status_code)
    print("CREATE RESPONSE:", response.text)

    return True

# =============================
# ROUTE - GENERATE ONLY
# =============================
@app.route("/", methods=["GET", "POST"])
def index():

    generated_cases = []
    existing_cases = []
    message = ""
    ticket_id = ""
    ticket_data = None

    if request.method == "POST":

        ticket_id = request.form.get("ticket_id")

        ticket_data = get_ticket_details(ticket_id)
        existing_cases = get_existing_testcases(ticket_id)

        if not ticket_data:
            message = "❌ Ticket Data Not Found"
            return render_template("index.html",
                                   cases=[],
                                   message=message,
                                   ticket_id=ticket_id,
                                   ticket_data=None)

        try:
            generated_cases = generate_test_cases(ticket_data, existing_cases)
            message = "✅ Test Cases Generated Successfully (Review & Approve)"
        except Exception as e:
            message = f"❌ Error: {str(e)}"

    return render_template("index.html",
                           cases=generated_cases,
                           existing_cases=existing_cases or [],
                           message=message,
                           ticket_id=ticket_id,
                           ticket_data=ticket_data)


# =============================
# ROUTE - APPROVE
# =============================
@app.route("/approve", methods=["POST"])
def approve():

    data = request.get_json()
    print("APPROVE DATA:", data)

    ticket_id = data.get("ticket_id")
    cases = data.get("cases", [])

    success_count = 0
    failed_count = 0

    for case in cases:
        result = create_and_link_testcase(ticket_id, case)
        if result:
            success_count += 1
        else:
            failed_count += 1

    if failed_count > 0:
        return jsonify({
            "status": "partial",
            "message": f"{success_count} added, {failed_count} failed"
        }), 500

    return jsonify({
        "status": "success",
        "message": f"{success_count} test cases added"
    })


if __name__ == "__main__":
    app.run(debug=True)