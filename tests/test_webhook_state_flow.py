import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi import BackgroundTasks

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app import webhook as webhook_module


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def text_payload(sender="27999999999", body="hello"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": sender,
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def button_payload(sender="27999999999", button_id="confirm", title="Confirm"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": sender,
                                    "type": "interactive",
                                    "interactive": {
                                        "button_reply": {
                                            "id": button_id,
                                            "title": title,
                                        }
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def member(**overrides):
    data = {
        "id": 42,
        "phone": "27999999999",
        "first_name": "Lindsay",
        "last_name": "Bull",
        "participation_type": "RUNNER",
        "profile_state": None,
        "popia_acknowledged": True,
        "last_seen_whats_new_version": None,
    }
    data.update(overrides)
    return data


def submission(**overrides):
    data = {
        "id": 101,
        "member_id": 42,
        "activity": "TT",
        "status": "PENDING",
        "tt_code_verified": True,
        "distance_text": None,
        "time_text": "",
        "seconds": 0,
    }
    data.update(overrides)
    return data


class WebhookStateFlowTests(unittest.IsolatedAsyncioTestCase):
    async def call_webhook(self, payload, member_data=None, submission_data=None, **patches):
        background_tasks = BackgroundTasks()

        with ExitStack() as stack:
            mocks = {
                name: stack.enter_context(patch.object(webhook_module, name))
                for name in [
                    "send_text",
                    "send_distance_buttons",
                    "send_confirm_buttons",
                    "send_participation_buttons",
                    "send_profile_buttons",
                    "send_both_submission_buttons",
                    "send_main_menu_list",
                    "save_member_name",
                    "set_profile_state",
                    "clear_profile_state",
                    "reopen_submission_for_edit",
                    "verify_tt_code",
                    "release_pending_submissions",
                    "mark_attendance",
                    "save_distance",
                    "save_time",
                    "confirm_submission",
                    "get_previous_best",
                    "get_runner_leaderboard",
                    "get_overall_leaderboard",
                    "get_season_pb_leaderboard",
                    "get_walker_feed",
                    "get_user_profile",
                    "has_seen_whats_new",
                    "mark_whats_new_seen",
                ]
            }
            mocks["has_seen_whats_new"].return_value = True

            stack.enter_context(patch.object(webhook_module, "get_member", return_value=member_data or member()))
            stack.enter_context(patch.object(webhook_module, "create_member", side_effect=AssertionError))
            get_or_create_value = submission_data or submission()
            get_or_create_mock = stack.enter_context(
                patch.object(webhook_module, "get_or_create_submission")
            )
            if isinstance(get_or_create_value, list):
                get_or_create_mock.side_effect = get_or_create_value
            else:
                get_or_create_mock.return_value = get_or_create_value

            stack.enter_context(patch.object(webhook_module, "ensure_tt_open", return_value=(True, None)))

            for name, value in patches.items():
                if name in mocks:
                    mocks[name].side_effect = None
                    mocks[name].return_value = value
                else:
                    stack.enter_context(patch.object(webhook_module, name, value))

            result = await webhook_module.webhook(FakeRequest(payload), background_tasks)

        return result, mocks, background_tasks

    async def test_verified_runner_resending_code_prompts_distance(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            submission_data=submission(distance_text=None, time_text=""),
        )

        self.assertEqual(result, {"status": "recover_awaiting_distance"})
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")
        mocks["send_text"].assert_not_called()

    async def test_help_menu_for_member(self):
        result, mocks, _ = await self.call_webhook(text_payload(body="\\Help"))

        self.assertEqual(result, {"status": "help"})
        mocks["send_main_menu_list"].assert_called_once_with("27999999999", False)
        mocks["send_text"].assert_not_called()

    async def test_help_menu_for_admin_includes_admin_commands(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(sender="27722135094", body="menu"),
            member_data=member(phone="27722135094"),
        )

        self.assertEqual(result, {"status": "help"})
        mocks["send_main_menu_list"].assert_called_once_with("27722135094", True)

    async def test_help_menu_falls_back_to_text_if_list_send_fails(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="HELP"),
            send_main_menu_list=False,
        )

        self.assertEqual(result, {"status": "help"})
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Irene AC Bot Menu", sent)
        self.assertIn("1 - Submit TT result", sent)

    async def test_unknown_button_during_pending_submission_recovers_prompt(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="not_expected", title="Old button"),
            submission_data=submission(distance_text=None, time_text=""),
        )

        self.assertEqual(result, {"status": "unknown_button_awaiting_distance"})
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_runner_with_distance_and_bad_time_gets_format_hint(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="soon"),
            submission_data=submission(distance_text="4", time_text=""),
        )

        self.assertEqual(result, {"status": "bad_time"})
        mocks["send_text"].assert_called_once_with("27999999999", "⏱ Format: 27:41 or 01:27:41")

    async def test_runner_valid_code_checks_in_and_prompts_distance(self):
        unverified = submission(tt_code_verified=False)
        verified = submission(tt_code_verified=True)

        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            submission_data=[unverified, verified],
            is_valid_tt_code=lambda _code: True,
            verify_tt_code=verified,
            release_pending_submissions=lambda _member_id: None,
            mark_attendance=lambda _member_id: None,
        )

        self.assertEqual(result, {"status": "code_ok_distance"})
        mocks["send_text"].assert_called_once_with("27999999999", "✅ Checked in!")
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_runner_valid_code_sends_whats_new_once_when_unseen(self):
        unverified = submission(tt_code_verified=False)
        verified = submission(tt_code_verified=True)

        result, mocks, _ = await self.call_webhook(
            text_payload(body="9793"),
            submission_data=[unverified, verified],
            is_valid_tt_code=lambda _code: True,
            verify_tt_code=verified,
            release_pending_submissions=lambda _member_id: None,
            mark_attendance=lambda _member_id: None,
            has_seen_whats_new=False,
        )

        self.assertEqual(result, {"status": "code_ok_distance"})
        self.assertEqual(mocks["send_text"].call_count, 2)
        self.assertEqual(mocks["send_text"].call_args_list[0].args, ("27999999999", "✅ Checked in!"))
        whats_new = mocks["send_text"].call_args_list[1].args[1]
        self.assertIn("What’s new", whats_new)
        mocks["mark_whats_new_seen"].assert_called_once_with(42, webhook_module.WHATS_NEW_VERSION)
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_menu_submit_shortcut_asks_for_code_when_not_checked_in(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="1"),
            submission_data=submission(tt_code_verified=False),
        )

        self.assertEqual(result, {"status": "menu_submit_await_code"})
        mocks["send_text"].assert_called_once_with("27999999999", "🔑 Send tonight's TT code to check in.")

    async def test_menu_profile_shortcut_opens_profile(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="2"),
            get_user_profile={"total_runs": 0, "pbs": [], "recent": []},
        )

        self.assertEqual(result, {"status": "profile"})
        mocks["send_profile_buttons"].assert_called_once()

    async def test_menu_leaderboard_shortcut_sends_leaderboard(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="4"),
            get_runner_leaderboard=[],
            get_walker_feed=[],
        )

        self.assertEqual(result, {"status": "leaderboard"})
        mocks["send_text"].assert_called_once()

    async def test_menu_overall_leaderboard_marks_member_rank(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="5"),
            get_overall_leaderboard=[
                {
                    "member_id": 7,
                    "first_name": "Asha",
                    "last_name": "Runner",
                    "distance_text": "8",
                    "time_text": "35:10",
                    "best_seconds": 2110,
                    "position": 1,
                },
                {
                    "member_id": 42,
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "distance_text": "8",
                    "time_text": "42:00",
                    "best_seconds": 2520,
                    "position": 11,
                },
            ],
        )

        self.assertEqual(result, {"status": "overall_leaderboard"})
        mocks["get_overall_leaderboard"].assert_called_once_with(42)
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Overall TT Leaderboard", sent)
        self.assertIn("Asha Runner", sent)
        self.assertIn("Lindsay Bull — 42:00 ← you", sent)

    async def test_season_pbs_command_sends_season_leaderboard(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="season pbs"),
            get_season_pb_leaderboard=[
                {
                    "member_id": 42,
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "distance_text": "4",
                    "time_text": "27:41",
                    "best_seconds": 1661,
                    "position": 1,
                },
            ],
        )

        self.assertEqual(result, {"status": "season_pb"})
        mocks["get_season_pb_leaderboard"].assert_called_once()
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Season PB Leaderboard", sent)
        self.assertIn("Lindsay Bull", sent)

    async def test_progress_command_sends_personal_progress(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="3"),
            get_user_profile={
                "total_runs": 6,
                "latest": {
                    "distance_text": "4",
                    "time_text": "27:41",
                    "seconds": 1661,
                },
                "pbs": [
                    {
                        "distance_text": "4",
                        "best_seconds": 1661,
                    }
                ],
                "recent": [],
            },
        )

        self.assertEqual(result, {"status": "progress"})
        sent = mocks["send_text"].call_args.args[1]
        self.assertIn("Lindsay, your progress", sent)
        self.assertIn("Latest: 4km — 27:41", sent)

    async def test_list_menu_progress_selection_sends_personal_progress(self):
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="menu_progress", title="My progress"),
            get_user_profile={
                "total_runs": 0,
                "latest": None,
                "pbs": [],
                "recent": [],
            },
        )

        self.assertEqual(result, {"status": "progress"})
        mocks["send_text"].assert_called_once()

    async def test_runner_distance_then_time_prompts_confirmation(self):
        with self.subTest("distance button"):
            updated = submission(distance_text="4", time_text="")
            result, mocks, _ = await self.call_webhook(
                button_payload(button_id="4km", title="4 km"),
                submission_data=submission(distance_text=None, time_text=""),
                save_distance=updated,
            )

            self.assertEqual(result, {"status": "distance"})
            mocks["save_distance"].assert_called_once_with(101, "4")
            mocks["send_text"].assert_called_once_with("27999999999", "⏱ Send your time.")

        with self.subTest("time text"):
            saved = submission(distance_text="4", time_text="27:41", seconds=1661)
            result, mocks, _ = await self.call_webhook(
                text_payload(body="27:41"),
                submission_data=submission(distance_text="4", time_text=""),
                save_time=saved,
            )

            self.assertEqual(result, {"status": "confirm"})
            mocks["save_time"].assert_called_once_with(101, "27:41", 1661)
            mocks["send_confirm_buttons"].assert_called_once_with("27999999999", "4", "27:41")

    async def test_walker_logs_workout(self):
        saved = submission(distance_text=None, time_text="Easy 5km walk", seconds=0)
        completed = submission(status="COMPLETE", distance_text=None, time_text="Easy 5km walk", seconds=0)

        result, mocks, _ = await self.call_webhook(
            text_payload(body="Easy 5km walk"),
            member_data=member(participation_type="WALKER"),
            submission_data=submission(distance_text=None, time_text=""),
            save_time=saved,
            confirm_submission=completed,
        )

        self.assertEqual(result, {"status": "walker_done"})
        mocks["save_time"].assert_called_once_with(101, "EASY 5KM WALK", 0)
        mocks["confirm_submission"].assert_called_once_with(101)
        mocks["send_text"].assert_called_once_with("27999999999", "🚶 Workout logged! Well done.")

    async def test_both_user_can_choose_distance_or_workout(self):
        with self.subTest("distance choice"):
            result, mocks, _ = await self.call_webhook(
                button_payload(button_id="submit_distance", title="Distance"),
                member_data=member(participation_type="BOTH"),
                submission_data=submission(distance_text=None, time_text=""),
            )

            self.assertEqual(result, {"status": "both_distance"})
            mocks["clear_profile_state"].assert_called_once_with(42)
            mocks["send_distance_buttons"].assert_called_once_with("27999999999")

        with self.subTest("workout choice"):
            result, mocks, _ = await self.call_webhook(
                button_payload(button_id="submit_workout", title="Workout"),
                member_data=member(participation_type="BOTH"),
                submission_data=submission(distance_text=None, time_text=""),
            )

            self.assertEqual(result, {"status": "both_workout"})
            mocks["send_text"].assert_called_once_with("27999999999", "🚶 Describe your workout.")

    async def test_profile_name_edit_clears_state(self):
        result, mocks, _ = await self.call_webhook(
            text_payload(body="Lindsay Bull"),
            member_data=member(profile_state="EDIT_NAME"),
        )

        self.assertEqual(result, {"status": "profile_name_updated"})
        mocks["save_member_name"].assert_called_once_with(42, "Lindsay", "Bull")
        mocks["clear_profile_state"].assert_called_once_with(42)
        mocks["send_text"].assert_called_once_with("27999999999", "✅ Name updated.")

    async def test_complete_submission_edit_reopens_and_prompts_distance(self):
        reopened = submission(status="PENDING", distance_text=None, time_text="")
        result, mocks, _ = await self.call_webhook(
            button_payload(button_id="edit", title="Edit"),
            submission_data=submission(
                status="COMPLETE",
                distance_text="4",
                time_text="27:41",
                seconds=1661,
            ),
            reopen_submission_for_edit=reopened,
        )

        self.assertEqual(result, {"status": "edit_existing"})
        mocks["reopen_submission_for_edit"].assert_called_once_with(101)
        mocks["send_distance_buttons"].assert_called_once_with("27999999999")

    async def test_confirm_replies_fast_and_schedules_followups(self):
        completed = submission(
            status="COMPLETE",
            distance_text="4",
            time_text="27:41",
            seconds=1661,
        )

        result, mocks, background_tasks = await self.call_webhook(
            button_payload(button_id="confirm", title="Confirm"),
            submission_data=submission(distance_text="4", time_text="27:41", seconds=1661),
            get_previous_best=1800,
            confirm_submission=completed,
        )

        self.assertEqual(result, {"status": "done"})
        mocks["send_text"].assert_called_once_with("27999999999", "🔥 TT recorded!")
        mocks["get_runner_leaderboard"].assert_not_called()
        self.assertEqual(len(background_tasks.tasks), 1)

    async def test_post_confirm_followup_sends_fallback_coach_message(self):
        messages = []

        with ExitStack() as stack:
            stack.enter_context(patch.object(webhook_module, "send_text", side_effect=lambda _to, body: messages.append(body)))
            stack.enter_context(
                patch.object(
                    webhook_module,
                    "get_user_profile",
                    return_value={
                        "total_runs": 5,
                        "recent": [{"seconds": 1600}, {"seconds": 1660}, {"seconds": 1720}],
                    },
                )
            )
            stack.enter_context(patch.object(webhook_module, "coach_reply", return_value="Keep building steadily."))
            stack.enter_context(
                patch.object(
                    webhook_module,
                    "get_runner_leaderboard",
                    return_value=[
                        {
                            "member_id": 42,
                            "distance_text": "4",
                            "position": 2,
                        }
                    ],
                )
            )
            stack.enter_context(patch.object(webhook_module, "get_walker_feed", return_value=[]))

            webhook_module.send_post_confirm_messages(
                "27999999999",
                member(),
                submission(status="COMPLETE", distance_text="4", time_text="27:41", seconds=1661),
                previous_best=1800,
            )

        self.assertEqual(len(messages), 1)
        self.assertIn("🔥 *Lindsay, here’s your TT recap*", messages[0])
        self.assertIn("4km — 27:41", messages[0])
        self.assertIn("Pace: 6:55/km", messages[0])
        self.assertIn("🚀 PB by 2:19", messages[0])
        self.assertIn("Season TTs: 5", messages[0])
        self.assertIn("🏆 Position: 2", messages[0])
        self.assertIn("🎉 Milestone: 5 TTs logged", messages[0])
        self.assertIn("🥇 Badge: 4km PB", messages[0])
        self.assertIn("🧠 Coach: Keep building steadily.", messages[0])


if __name__ == "__main__":
    unittest.main()
