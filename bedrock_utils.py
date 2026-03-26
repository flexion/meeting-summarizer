#!/usr/bin/env python3
"""
AWS Bedrock utilities for meeting summarization.

This module provides shared functionality for interacting with AWS Bedrock
to generate meeting summaries and chat with transcripts.
"""

import json
import os
from typing import cast

import boto3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# AWS Bedrock Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0")


def summarize_transcript(transcript_text: str) -> str | None:
    """Summarize transcript using AWS Bedrock.

    Args:
        transcript_text: The plain text transcript to summarize.

    Returns:
        Formatted summary text with key points and action items, or None if summarization failed.
    """
    if not transcript_text.strip():
        return None

    try:
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

        prompt = (
            """Please summarize this meeting transcript. Provide:

1. **Key Points** - Main topics and decisions discussed (bullet points)
2. **Action Items** - Any tasks, follow-ups, or commitments mentioned (bullet points with owner if mentioned)

Keep it concise and actionable.

Transcript:
"""
            + transcript_text
        )

        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                }
            ),
        )

        result = json.loads(response["body"].read())
        return cast(str, result["content"][0]["text"])

    except Exception as e:
        print(f"\n⚠️  Summarization error: {e}")
        print("   Transcript saved but summary generation failed.")
        print("   Check AWS credentials and Bedrock access.")
        return None
