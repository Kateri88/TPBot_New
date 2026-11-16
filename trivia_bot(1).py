#!/usr/bin/env python3
"""
IFUNNY TEXT TRIVIA BOT - single-file Python trivia game

Python 3.10+
No third-party packages required.

IMPORTANT:
This file contains the complete trivia game engine and a simple terminal adapter.
It does NOT automatically connect to iFunny. A live iFunny connection requires an
official/supported bot API, webhook, or chat integration. Do not automate iFunny
by scraping, stealing session cookies, or pretending this script is running inside
the app. When a supported interface is available, call handle_message(username, text)
for each incoming chat message and send each returned string back to the room.

Run locally:
    python trivia_bot.py

Optional admin password:
    Set environment variable TRIVIA_ADMIN_PASSWORD before starting the program.
    Example (Windows PowerShell):
        $env:TRIVIA_ADMIN_PASSWORD="your-strong-password"
        python trivia_bot.py
    Example (macOS/Linux):
        TRIVIA_ADMIN_PASSWORD="your-strong-password" python3 trivia_bot.py

Terminal adapter:
    Type messages as: username: message
    Example: Alex: !trivia
    Type /quit to exit the local test console.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import secrets
import shlex
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

APP_NAME = "iFunny Text Trivia"
DATA_FILE = Path(__file__).with_name("trivia_data.json")
DEFAULT_ADMIN_PASSWORD = "change-me-now"
ADMIN_PASSWORD = os.environ.get("TRIVIA_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

# Edit this list to add, remove, or change trivia questions.
# Correct answers are stored internally and are never shown before a question ends.
QUESTIONS = [
    {"category": "General", "question": "What is the largest planet in our solar system?",
     "answers": ["Mars", "Jupiter", "Saturn", "Venus"], "correct": "B", "explanation": "Jupiter is the largest planet."},
    {"category": "Science", "question": "What is the chemical symbol for gold?",
     "answers": ["Ag", "Gd", "Au", "Go"], "correct": "C", "explanation": "Au comes from the Latin word aurum."},
    {"category": "Geography", "question": "What is the capital of Japan?",
     "answers": ["Seoul", "Beijing", "Bangkok", "Tokyo"], "correct": "D", "explanation": "Tokyo is the capital of Japan."},
    {"category": "Movies", "question": "In the original Star Wars trilogy, what is the name of Han Solo's ship?",
     "answers": ["The Enterprise", "Millennium Falcon", " Serenity", "The TARDIS"], "correct": "B", "explanation": "Han Solo pilots the Millennium Falcon."},
    {"category": "Animals", "question": "What is the fastest land animal?",
     "answers": ["Cheetah", "Lion", "Horse", "Gazelle"], "correct": "A", "explanation": "The cheetah is the fastest land animal."},
    {"category": "History", "question": "Which ancient civilization built the pyramids at Giza?",
     "answers": ["Romans", "Greeks", "Ancient Egyptians", "Mayans"], "correct": "C", "explanation": "The pyramids at Giza were built in ancient Egypt."},
    {"category": "Sports", "question": "How many players from one basketball team are on the court at a time?",
     "answers": ["4", "5", "6", "7"], "correct": "B", "explanation": "A basketball team has five players on the court."},
    {"category": "Food", "question": "Which fruit is traditionally used to make guacamole?",
     "answers": ["Avocado", "Cucumber", "Kiwi", "Pear"], "correct": "A", "explanation": "Avocado is the main ingredient in guacamole."},
    {"category": "Space", "question": "What is the name of Earth's natural satellite?",
     "answers": ["Europa", "Titan", "The Moon", "Phobos"], "correct": "C", "explanation": "Earth's natural satellite is the Moon."},
    {"category": "Literature", "question": "Who wrote 'Romeo and Juliet'?",
     "answers": ["Charles Dickens", "William Shakespeare", "Mark Twain", "Jane Austen"], "correct": "B", "explanation": "William Shakespeare wrote Romeo and Juliet."},
    {"category": "Technology", "question": "What does CPU stand for?",
     "answers": ["Computer Power Utility", "Central Processing Unit", "Core Program Upload", "Central Program User"], "correct": "B", "explanation": "CPU means Central Processing Unit."},
    {"category": "Nature", "question": "What gas do plants absorb from the atmosphere?",
     "answers": ["Oxygen", "Nitrogen", "Carbon dioxide", "Helium"], "correct": "C", "explanation": "Plants absorb carbon dioxide during photosynthesis."},
    {"category": "General", "question": "How many sides does a hexagon have?",
     "answers": ["5", "6", "7", "8"], "correct": "B", "explanation": "A hexagon has six sides."},
    {"category": "Geography", "question": "Which ocean is the largest?",
     "answers": ["Atlantic", "Indian", "Arctic", "Pacific"], "correct": "D", "explanation": "The Pacific Ocean is the largest."},
    {"category": "Music", "question": "How many strings does a standard guitar usually have?",
     "answers": ["4", "5", "6", "7"], "correct": "C", "explanation": "A standard guitar usually has six strings."},
]


def _password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)


@dataclass
class Question:
    category: str
    question: str
    answers: list[str]
    correct: str
    explanation: str = ""


class TriviaGame:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file
        self.players: dict[str, int] = {}
        self.admin_sessions: set[str] = set()
        self.is_running = False
        self.current_question: Optional[Question] = None
        self.question_number = 0
        self.round_questions: list[Question] = []
        self.used_questions: set[str] = set()
        self.answered_players: set[str] = set()
        self.last_winner: Optional[str] = None
        self._load_scores()

    def _load_scores(self) -> None:
        if not self.data_file.exists():
            return
        try:
            data = json.loads(self.data_file.read_text(encoding="utf-8"))
            saved = data.get("scores", {})
            if isinstance(saved, dict):
                self.players = {str(k): max(0, int(v)) for k, v in saved.items()}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            print("[Warning] Could not read saved scores; starting with an empty scoreboard.")

    def _save_scores(self) -> None:
        try:
            payload = {"scores": self.players}
            temp_file = self.data_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp_file.replace(self.data_file)
        except OSError as exc:
            print(f"[Warning] Could not save scores: {exc}")

    @staticmethod
    def _clean_name(username: str) -> str:
        return " ".join(str(username).strip().split())[:40] or "Player"

    def _say_question(self) -> list[str]:
        if not self.is_running:
            return ["Trivia is not running. An admin can start it with ?admin start."]
        if not self.round_questions:
            self.is_running = False
            self.current_question = None
            return ["There are no questions available. Add questions or edit the QUESTIONS list."]
        self.current_question = self.round_questions.pop(0)
        self.question_number += 1
        self.answered_players.clear()
        q = self.current_question
        lines = [
            f"TRIVIA QUESTION {self.question_number}",
            f"Category: {q.category}",
            q.question,
        ]
        lines.extend(f"?{letter} - {answer}" for letter, answer in zip("ABCD", q.answers))
        lines.append("Reply with ?A, ?B, ?C, or ?D.")
        lines.append("First correct answer earns 1 point. Good luck!")
        return lines

    def start(self) -> list[str]:
        if self.is_running:
            return ["Trivia is already running."]
        pool = [Question(**item) for item in QUESTIONS if len(item.get("answers", [])) == 4]
        if not pool:
            return ["No valid questions are loaded."]
        random.shuffle(pool)
        self.round_questions = pool
        self.used_questions.clear()
        self.question_number = 0
        self.is_running = True
        return ["TRIVIA IS STARTING!"] + self._say_question()

    def stop(self) -> list[str]:
        if not self.is_running:
            return ["Trivia is not currently running."]
        self.is_running = False
        self.current_question = None
        self.round_questions.clear()
        return ["Trivia has been stopped by an admin.", self.leaderboard_text()]

    def next_question(self) -> list[str]:
        if not self.is_running:
            return ["Trivia is not running."]
        if self.current_question:
            self._reveal_answer()
        return self._say_question()

    def _reveal_answer(self) -> list[str]:
        if not self.current_question:
            return []
        q = self.current_question
        answer_text = q.answers[ord(q.correct) - ord("A")]
        lines = [f"Correct answer: {q.correct}. {answer_text}."]
        if q.explanation:
            lines.append(q.explanation)
        self.current_question = None
        return lines

    def answer(self, username: str, choice: str) -> list[str]:
        name = self._clean_name(username)
        choice = choice.strip().upper()
        if choice.startswith("?"):
            choice = choice[1:].strip()
        if choice not in {"A", "B", "C", "D"}:
            return ["Use !answer A, !answer B, !answer C, or !answer D."]
        if not self.is_running or not self.current_question:
            return ["There is no active question right now."]
        if name.lower() in {p.lower() for p in self.answered_players}:
            return [f"{name}, your answer has already been recorded."]
        self.answered_players.add(name)
        if choice == self.current_question.correct:
            self.players[name] = self.players.get(name, 0) + 1
            self._save_scores()
            q = self.current_question
            answer_text = q.answers[ord(q.correct) - ord("A")]
            self.current_question = None
            self.last_winner = name
            result = [f"CORRECT! {name} gets 1 point. Answer: {choice}. {answer_text}."]
            if q.explanation:
                result.append(q.explanation)
            result.append("An admin can use ?admin next, or the next question will start when an admin advances it.")
            return result
        return [f"Sorry {name}, that's not correct. Keep trying if you have not used your answer yet."]

    def leaderboard_text(self) -> str:
        if not self.players:
            return "LEADERBOARD: No scores yet."
        ranked = sorted(self.players.items(), key=lambda item: (-item[1], item[0].lower()))
        lines = ["LEADERBOARD"]
        for place, (name, score) in enumerate(ranked[:10], start=1):
            lines.append(f"{place}. {name} - {score} point(s)")
        return "\n".join(lines)

    def help_text(self) -> str:
        return (
            "TRIVIA COMMANDS\n"
            "?trivia - start trivia if it is not running, or show the current question\n"
            "?A, ?B, ?C, or ?D - submit your multiple-choice answer\n"
            "?score - show your score\n"
            "?leaderboard - show the top 10 players\n"
            "?help - show commands\n"
            "ADMIN: ?admin login PASSWORD, ?admin start, ?admin stop, ?admin next, "
            "?admin add CATEGORY | QUESTION | A | B | C | D | CORRECT_LETTER | EXPLANATION, "
            "?admin reset_scores, ?admin logout"
        )

    def admin_command(self, username: str, args: list[str]) -> list[str]:
        name = self._clean_name(username)
        if not args:
            return ["Admin commands: login, start, stop, next, add, reset_scores, logout."]
        action = args[0].lower()

        if action == "login":
            supplied = " ".join(args[1:])
            if not supplied:
                return ["Usage: ?admin login YOUR_PASSWORD"]
            if hmac.compare_digest(supplied, ADMIN_PASSWORD):
                self.admin_sessions.add(name.lower())
                warning = []
                if ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
                    warning.append("WARNING: You are using the default admin password. Set TRIVIA_ADMIN_PASSWORD before using this in a real room.")
                return warning + [f"{name} is now logged in as an admin."]
            return ["Incorrect admin password."]

        if action == "logout":
            self.admin_sessions.discard(name.lower())
            return [f"{name} has been logged out of admin mode."]

        if name.lower() not in self.admin_sessions:
            return ["Admin access required. Log in with ?admin login YOUR_PASSWORD."]

        if action == "start":
            return self.start()
        if action == "stop":
            return self.stop()
        if action == "next":
            return self.next_question()
        if action == "reset_scores":
            self.players.clear()
            self._save_scores()
            return ["All player scores have been reset."]
        if action == "add":
            raw = " ".join(args[1:])
            parts = [part.strip() for part in raw.split("|")]
            if len(parts) < 8:
                return ["Usage: ?admin add CATEGORY | QUESTION | OPTION A | OPTION B | OPTION C | OPTION D | CORRECT LETTER | EXPLANATION"]
            category, question, a, b, c, d, correct = parts[:7]
            explanation = " | ".join(parts[7:])
            correct = correct.upper()
            if correct not in {"A", "B", "C", "D"}:
                return ["Correct letter must be A, B, C, or D."]
            QUESTIONS.append({
                "category": category or "Custom",
                "question": question,
                "answers": [a, b, c, d],
                "correct": correct,
                "explanation": explanation,
            })
            return [f"Added a question in category '{category or 'Custom'}'. It will be available in the next game."]
        return ["Unknown admin command. Use ?admin for the admin command list."]

    def handle_message(self, username: str, message: str) -> list[str]:
        """Main integration point: pass in a chat username and message; get reply lines."""
        name = self._clean_name(username)
        msg = str(message).strip()
        if not msg:
            return []
        lower = msg.lower()

        if lower in {"?help", "?commands"}:
            return [self.help_text()]
        if lower == "?leaderboard":
            return [self.leaderboard_text()]
        if lower == "?score":
            return [f"{name}, your score is {self.players.get(name, 0)} point(s)."]
        if lower == "?trivia":
            if not self.is_running:
                return self.start()
            if self.current_question:
                q = self.current_question
                lines = [f"TRIVIA QUESTION {self.question_number}", f"Category: {q.category}", q.question]
                lines.extend(f"?{letter} - {answer}" for letter, answer in zip("ABCD", q.answers))
                lines.append("Reply with ?A, ?B, ?C, or ?D.")
                return lines
            return ["The current question has been answered. An admin can use ?admin next to post the next question."]
        if lower in {"?a", "?b", "?c", "?d"}:
            return self.answer(name, msg[1:].strip())
        if lower.startswith("?admin"):
            try:
                args = shlex.split(msg[6:].strip())
            except ValueError:
                return ["Could not read that admin command. Check your quotation marks."]
            return self.admin_command(name, args)
        return []


def run_terminal() -> None:
    print("=" * 58)
    print(f"{APP_NAME} - local test mode")
    print("=" * 58)
    print("This is a local test console, not a live iFunny connection.")
    print("Enter chat messages as username: message")
    print("Example: Jamie: !help")
    print("Type /quit to exit.")
    if ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
        print("SECURITY WARNING: Default admin password is 'change-me-now'.")
        print("Set TRIVIA_ADMIN_PASSWORD to a strong password before using this.")
    game = TriviaGame()

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        if raw.lower() == "/quit":
            print("Goodbye.")
            break
        if ":" not in raw:
            print("Format must be username: message")
            continue
        username, message = raw.split(":", 1)
        replies = game.handle_message(username.strip(), message.strip())
        for reply in replies:
            print(reply)
        if not replies:
            print("(No bot response; message did not match a game command.)")


# ---------------------------------------------------------------------------
# FUTURE IFUNNY API CONNECTION POINT
# ---------------------------------------------------------------------------
# This game is deliberately separated from the chat platform. When you obtain
# access to an official/supported iFunny API, webhook, or bot interface:
#
# 1. Create one TriviaGame instance when your bot starts.
# 2. For every incoming room message, call:
#       replies = game.handle_message(sender_username, message_text)
# 3. Send each reply back to the same room using the API's send-message method.
#
# Example adapter shape (pseudocode - replace these two API calls with the
# actual method names and authentication required by iFunny's supported API):
#
# game = TriviaGame()
#
# def on_ifunny_message(event):
#     username = event["sender"]["name"]
#     message_text = event["message"]["text"]
#     room_id = event["room"]["id"]
#
#     for reply in game.handle_message(username, message_text):
#         ifunny_api.send_message(room_id=room_id, text=reply)
#
# def start_ifunny_bot():
#     ifunny_api.authenticate(api_key=os.environ["IFUNNY_API_KEY"])
#     ifunny_api.listen_for_messages(on_ifunny_message)
#
# Keep API keys in environment variables or a secrets manager. Never paste
# private API keys, passwords, or session cookies into this source file.
# No real iFunny endpoint, authentication scheme, or SDK is assumed here:
# fill in the adapter only after you have official API documentation/access.

if __name__ == "__main__":
    run_terminal()
