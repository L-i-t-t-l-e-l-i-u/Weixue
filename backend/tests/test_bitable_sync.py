import json
import os
import shutil
import tempfile
import unittest
import atexit
from types import SimpleNamespace

# Isolate the database before importing the models. NOTE: this is the first
# module-level WEIXUE_DB_PATH in the suite, so the shared engine binds to this
# directory for every test module; it must only be removed at process exit.
_TMP_DIR = tempfile.mkdtemp(prefix="weixue_bitable_test_")
os.environ["WEIXUE_DB_PATH"] = os.path.join(_TMP_DIR, "test.db")
atexit.register(shutil.rmtree, _TMP_DIR, True)

import httpx

from database import (
    Course,
    DebateTopic,
    FeishuBinding,
    Student,
    StudentResponse,
    SessionLocal,
)
from feishu.client import FeishuClient, FeishuConfig

# feishu.client's import runs load_dotenv on backend/.env; purge any real
# credentials so "unconfigured" tests stay deterministic on machines that
# already have live Feishu config.
for _key in [k for k in os.environ if k.startswith("FEISHU_")]:
    os.environ.pop(_key, None)

from feishu.sync import (
    BitableSyncer,
    TEACHER_FIELDS_BY_TABLE,
    _field_list,
    _field_str,
    _parse_score_summary,
    bitable_is_configured,
    bitable_status,
    build_course_record,
    build_response_record,
    build_student_record,
    build_topic_record,
    teacher_fields_hash,
)


def _reset_db():
    """Drop and recreate all tables so rows/bindings never leak across classes."""
    from database import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _configured_client(calls: dict) -> tuple[FeishuClient, httpx.AsyncClient]:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal/"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "tenant_access_token": "t-test-token",
                    "expire": 7200,
                },
            )
        if request.url.path.endswith("/records/search"):
            calls.setdefault("search", []).append(request.url.path)
            # path: /bitable/v1/apps/{app}/tables/{table_id}/records/search
            table_id = request.url.path.split("/")[-3]
            records = calls.get("remote_records", {}).get(table_id, [])
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "items": records,
                        "has_more": False,
                        "page_token": "",
                        "total": len(records),
                    },
                },
            )
        if request.url.path.endswith("/records/batch_create"):
            calls["create"].append(json.loads(request.content.decode()))
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "data": {
                        "records": [{"record_id": f"rec_{len(calls['create'])}"}]
                    },
                },
            )
        if request.url.path.endswith("/records/batch_update"):
            calls["update"].append(json.loads(request.content.decode()))
            return httpx.Response(
                200, json={"code": 0, "msg": "success", "data": {"records": []}}
            )
        return httpx.Response(
            404, json={"code": 99999, "msg": "unexpected path: " + request.url.path}
        )

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://example.test")
    config = FeishuConfig()
    config.app_id = "cli_test"
    config.app_secret = "secret"
    config.base_url = "https://example.test"
    config.bitable_app_token = "bascn_test"
    config.bitable_table_ids = {
        "courses": "tbl_courses",
        "topics": "tbl_topics",
        "students": "tbl_students",
        "responses": "tbl_responses",
    }
    client = FeishuClient(config, http_client=http)
    return client, http


def _unconfigured_client() -> FeishuClient:
    config = FeishuConfig()
    config.app_id = ""
    config.app_secret = ""
    return FeishuClient(config, http_client=httpx.AsyncClient())


class RecordBuilderTests(unittest.TestCase):
    def test_course_record(self):
        course = SimpleNamespace(
            class_name="思辨一班", grade_level=3, created_at=None
        )
        fields = build_course_record(course)["fields"]
        self.assertEqual(fields["班级名"], "思辨一班")
        self.assertEqual(fields["年级"], 3)
        self.assertIsInstance(fields["创建时间"], int)

    def test_topic_record_uses_chinese_labels(self):
        topic = SimpleNamespace(
            title="动物应该养在动物园吗？",
            topic_type="dilemma",
            cognitive_tier="developing",
            stimulus_material="材料",
            reference_arguments=["正方一", "反方一"],
            order=1,
        )
        fields = build_topic_record(topic)["fields"]
        self.assertEqual(fields["标题"], "动物应该养在动物园吗？")
        self.assertEqual(fields["类型"], "两难")
        self.assertEqual(fields["认知梯段"], "发展层")
        self.assertIn("正方一", fields["参考论据"])

    def test_student_record(self):
        student = SimpleNamespace(
            name="小雨",
            grade=2,
            cognitive_tier="basic",
            course=SimpleNamespace(class_name="思辨一班"),
            comment_draft="",
        )
        fields = build_student_record(student)["fields"]
        self.assertEqual(fields["姓名"], "小雨")
        self.assertEqual(fields["认知梯段"], "基础层")
        self.assertEqual(fields["班级"], "思辨一班")

    def test_response_record_status_and_multi_select(self):
        response = SimpleNamespace(
            teacher_reviewed=True,
            ai_dimension_scores={"position": "A", "material": "A-", "structure": "B+", "language": "A-", "perspective": "B+"},
            ai_confidence="certain_good",
            ai_suggested_tags=["结构清晰", "选材具体"],
            ai_bonus_flags=["有新意"],
            teacher_dimension_scores={"position": "A"},
            teacher_tags=["选材具体"],
            teacher_note="表达流畅",
            raw_text="原文",
            cleaned_text="清洗稿",
            source="asr",
        )
        student = SimpleNamespace(name="小雨")
        topic = SimpleNamespace(title="动物应该养在动物园吗？")
        fields = build_response_record(response, student, topic)["fields"]
        self.assertEqual(fields["学生"], "小雨")
        self.assertEqual(fields["来源"], "音频转写")
        self.assertEqual(fields["AI置信度"], "高")
        self.assertEqual(fields["状态"], "教师已审")
        self.assertEqual(fields["AI建议标签"], ["结构清晰", "选材具体"])
        self.assertEqual(fields["加分项"], ["有新意"])
        self.assertIn("立意:A", fields["AI评分摘要"])


class BitableSyncTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        _reset_db()

    # NOTE: the temp DB dir is shared by the whole suite's engine; cleanup is
    # registered at module level via atexit, never in a tearDownClass.

    def _seed_course(self, db):
        course = Course(title="测试课程", class_name="思辨一班", grade_level=3)
        db.add(course)
        db.flush()
        topic = DebateTopic(
            course_id=course.id,
            title="动物应该养在动物园吗？",
            topic_type="dilemma",
            cognitive_tier="developing",
        )
        db.add(topic)
        db.flush()
        student = Student(course_id=course.id, name="小雨", grade=2)
        db.add(student)
        db.flush()
        response = StudentResponse(
            student_id=student.id,
            topic_id=topic.id,
            raw_text="我觉得应该放回野外。",
            cleaned_text="我觉得应该放回野外。",
            source="manual",
            ai_dimension_scores={"position": "A"},
            ai_confidence="uncertain",
            ai_suggested_tags=["结构清晰"],
            teacher_reviewed=True,
            teacher_dimension_scores={"position": "A"},
        )
        db.add(response)
        db.commit()
        return course.id

    async def test_sync_course_creates_then_updates(self):
        calls = {"create": [], "update": []}
        client, http = _configured_client(calls)
        db = SessionLocal()
        try:
            course_id = self._seed_course(db)
            syncer = BitableSyncer(client)
            self.assertTrue(syncer.available)

            first = await syncer.sync_course(db, course_id)
            self.assertTrue(first["configured"])
            self.assertEqual(
                first["tables"]["responses"], {"created": 1, "updated": 0, "errors": 0, "skipped": 0}
            )
            self.assertEqual(len(calls["create"]), 4)  # course, topic, student, response
            self.assertEqual(calls["update"], [])

            second = await syncer.sync_course(db, course_id)
            self.assertEqual(second["tables"]["responses"]["updated"], 1)
            self.assertEqual(len(calls["create"]), 4)  # no duplicates
            self.assertEqual(len(calls["update"]), 4)  # all entities updated

            bindings = db.query(FeishuBinding).all()
            self.assertEqual(len(bindings), 4)
            self.assertTrue(all(b.remote_record_id for b in bindings))
        finally:
            db.close()
            await http.aclose()

    async def test_sync_response_single(self):
        calls = {"create": [], "update": []}
        client, http = _configured_client(calls)
        db = SessionLocal()
        try:
            course_id = self._seed_course(db)
            response = (
                db.query(StudentResponse)
                .join(Student)
                .filter(Student.course_id == course_id)
                .first()
            )
            syncer = BitableSyncer(client)
            result = await syncer.sync_response(db, response.id)
            self.assertEqual(result["tables"]["responses"]["created"], 1)
            self.assertEqual(len(calls["create"]), 1)
        finally:
            db.close()
            await http.aclose()

    async def test_unconfigured_sync_is_safe(self):
        calls = {"create": [], "update": []}
        client, http = _configured_client(calls)
        db = SessionLocal()
        try:
            course_id = self._seed_course(db)
            unconfigured = _unconfigured_client()
            try:
                syncer = BitableSyncer(unconfigured)
                self.assertFalse(syncer.available)
                result = await syncer.sync_course(db, course_id)
                self.assertFalse(result["configured"])
                self.assertEqual(result["mode"], "deferred")
                self.assertEqual(calls["create"], [])  # no network calls at all
            finally:
                await unconfigured._http.aclose()
        finally:
            db.close()
            await http.aclose()

    def test_status_and_configuration_helpers(self):
        config = FeishuConfig()
        self.assertFalse(bitable_is_configured(config))
        status = bitable_status(config)
        self.assertEqual(status["mode"], "deferred")
        self.assertFalse(status["configured"])


class PullHelperTests(unittest.TestCase):
    def test_parse_score_summary_round_trip(self):
        scores = _parse_score_summary("立意:A；选材:B+；结构：A-")
        self.assertEqual(scores, {"position": "A", "material": "B+", "structure": "A-"})

    def test_parse_score_summary_tolerates_junk(self):
        self.assertEqual(_parse_score_summary(""), {})
        self.assertEqual(_parse_score_summary("；；"), {})
        # Unknown labels are kept verbatim; segments without a grade are skipped.
        scores = _parse_score_summary("自定义维度:A；坏的段；立意:B")
        self.assertEqual(scores, {"自定义维度": "A", "position": "B"})

    def test_field_readers_tolerate_read_shapes(self):
        self.assertEqual(_field_str("  x "), "x")
        self.assertEqual(_field_str({"text": "y"}), "y")
        self.assertEqual(_field_str(None), "")
        self.assertEqual(_field_list(["a", {"text": "b"}]), ["a", "b"])
        self.assertEqual(_field_list("solo"), ["solo"])
        self.assertEqual(_field_list(None), [])

    def test_hash_is_echo_stable(self):
        keys = TEACHER_FIELDS_BY_TABLE["responses"]
        push_shape = {"教师评分": "立意:A", "教师标签": ["选材具体"], "教师批注": "n", "状态": "教师已审"}
        # Same content read back in object/segment shapes must hash identically.
        read_shape = {
            "教师评分": {"text": "立意:A"},
            "教师标签": [{"text": "选材具体"}],
            "教师批注": "n",
            "状态": "教师已审",
        }
        self.assertEqual(teacher_fields_hash(push_shape, keys), teacher_fields_hash(read_shape, keys))
        self.assertNotEqual(
            teacher_fields_hash(push_shape, keys),
            teacher_fields_hash({**push_shape, "教师批注": "changed"}, keys),
        )


class BitablePullTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        _reset_db()

    def _seed_course(self, db, reviewed: bool = False):
        course = Course(title="拉取测试课程", class_name="思辨二班", grade_level=4)
        db.add(course)
        db.flush()
        topic = DebateTopic(
            course_id=course.id,
            title="动物园有必要吗？",
            topic_type="fact_opinion",
            cognitive_tier="developing",
        )
        db.add(topic)
        db.flush()
        student = Student(course_id=course.id, name="豆豆", grade=2)
        db.add(student)
        db.flush()
        response = StudentResponse(
            student_id=student.id,
            topic_id=topic.id,
            raw_text="我觉得动物园有必要。",
            cleaned_text="我觉得动物园有必要。",
            source="manual",
            ai_dimension_scores={"position": "B+"},
            ai_confidence="uncertain",
            ai_suggested_tags=[],
            teacher_reviewed=reviewed,
            teacher_dimension_scores={"position": "A"} if reviewed else None,
            teacher_note="本地批注" if reviewed else "",
        )
        db.add(response)
        db.commit()
        return course.id

    def _response_binding(self, db, course_id):
        resp = (
            db.query(StudentResponse)
            .join(Student)
            .filter(Student.course_id == course_id)
            .first()
        )
        binding = (
            db.query(FeishuBinding)
            .filter(
                FeishuBinding.entity_type == "response",
                FeishuBinding.entity_id == resp.id,
                FeishuBinding.table_key == "responses",
            )
            .first()
        )
        return resp, binding

    async def test_push_snapshots_hash_then_pull_applies_edits(self):
        calls = {"create": [], "update": [], "remote_records": {}}
        client, http = _configured_client(calls)
        db = SessionLocal()
        try:
            course_id = self._seed_course(db)
            syncer = BitableSyncer(client)
            await syncer.sync_course(db, course_id)
            resp, binding = self._response_binding(db, course_id)
            self.assertIsNotNone(binding)
            self.assertTrue(binding.last_synced_hash)  # echo baseline stored on push

            calls["remote_records"]["tbl_responses"] = [
                {
                    "record_id": binding.remote_record_id,
                    "fields": {
                        "教师评分": "立意:A+；选材:B+",
                        "教师标签": ["选材具体", "结构清晰"],
                        "教师批注": "表格里的批注",
                        "状态": "教师已审",
                    },
                }
            ]
            result = await syncer.pull_course(db, course_id)
            self.assertEqual(
                result["tables"]["responses"],
                {"checked": 1, "updated": 1, "unchanged": 0},
            )
            db.expire_all()
            resp = db.get(StudentResponse, resp.id)
            self.assertEqual(resp.teacher_dimension_scores, {"position": "A+", "material": "B+"})
            self.assertEqual(resp.teacher_tags, ["选材具体", "结构清晰"])
            self.assertEqual(resp.teacher_note, "表格里的批注")
            self.assertTrue(resp.teacher_reviewed)
        finally:
            db.close()
            await http.aclose()

    async def test_pull_echo_of_own_push_is_no_change(self):
        calls = {"create": [], "update": [], "remote_records": {}}
        client, http = _configured_client(calls)
        db = SessionLocal()
        try:
            course_id = self._seed_course(db)
            syncer = BitableSyncer(client)
            await syncer.sync_course(db, course_id)
            resp, binding = self._response_binding(db, course_id)

            # Remote still shows exactly what we pushed: no teacher edits.
            pushed = build_response_record(resp, resp.student, resp.topic)
            calls["remote_records"]["tbl_responses"] = [
                {"record_id": binding.remote_record_id, "fields": pushed["fields"]}
            ]
            result = await syncer.pull_course(db, course_id)
            counters = result["tables"]["responses"]
            self.assertEqual(counters["updated"], 0)
            self.assertEqual(counters["unchanged"], 1)
        finally:
            db.close()
            await http.aclose()

    async def test_pull_never_unreviews(self):
        calls = {"create": [], "update": [], "remote_records": {}}
        client, http = _configured_client(calls)
        db = SessionLocal()
        try:
            course_id = self._seed_course(db, reviewed=True)
            syncer = BitableSyncer(client)
            await syncer.sync_course(db, course_id)
            resp, binding = self._response_binding(db, course_id)

            calls["remote_records"]["tbl_responses"] = [
                {
                    "record_id": binding.remote_record_id,
                    "fields": {
                        "教师评分": "立意:B",
                        "教师标签": [],
                        "教师批注": "改过的批注",
                        "状态": "AI已评",  # teacher did NOT mark reviewed remotely
                    },
                }
            ]
            await syncer.pull_course(db, course_id)
            db.expire_all()
            resp = db.get(StudentResponse, resp.id)
            self.assertTrue(resp.teacher_reviewed)  # never un-reviewed
            self.assertEqual(resp.teacher_note, "改过的批注")  # other fields still import
            self.assertEqual(resp.teacher_dimension_scores, {"position": "B"})
        finally:
            db.close()
            await http.aclose()

    async def test_pull_unmatched_remote_rows_are_counted_not_created(self):
        calls = {"create": [], "update": [], "remote_records": {}}
        client, http = _configured_client(calls)
        db = SessionLocal()
        try:
            course_id = self._seed_course(db)
            syncer = BitableSyncer(client)
            await syncer.sync_course(db, course_id)
            before = db.query(StudentResponse).count()

            calls["remote_records"]["tbl_responses"] = [
                {
                    "record_id": "rec_unknown_row",
                    "fields": {"教师批注": "表格手加的行", "状态": "教师已审"},
                }
            ]
            result = await syncer.pull_course(db, course_id)
            self.assertEqual(result["unmatched_remote"], 1)
            self.assertEqual(result["tables"]["responses"]["updated"], 0)
            self.assertEqual(db.query(StudentResponse).count(), before)
        finally:
            db.close()
            await http.aclose()

    async def test_pull_legacy_binding_adopts_baseline_first(self):
        calls = {"create": [], "update": [], "remote_records": {}}
        client, http = _configured_client(calls)
        db = SessionLocal()
        try:
            course_id = self._seed_course(db, reviewed=True)
            resp = (
                db.query(StudentResponse)
                .join(Student)
                .filter(Student.course_id == course_id)
                .first()
            )
            # Simulate a pre-two-way binding: mapped but no hash baseline.
            legacy = FeishuBinding(
                entity_type="response",
                entity_id=resp.id,
                table_key="responses",
                remote_record_id="rec_legacy",
            )
            db.add(legacy)
            db.commit()
            syncer = BitableSyncer(client)

            calls["remote_records"]["tbl_responses"] = [
                {
                    "record_id": "rec_legacy",
                    "fields": {"教师评分": "", "教师标签": [], "教师批注": "", "状态": "待评估"},
                }
            ]
            result = await syncer.pull_course(db, course_id)
            self.assertEqual(result["tables"]["responses"]["updated"], 0)
            self.assertEqual(result["tables"]["responses"]["unchanged"], 1)
            db.expire_all()
            resp = db.get(StudentResponse, resp.id)
            self.assertEqual(resp.teacher_note, "本地批注")  # empty remote did NOT wipe local
            self.assertTrue(resp.teacher_reviewed)
            legacy = db.query(FeishuBinding).filter_by(remote_record_id="rec_legacy").first()
            self.assertTrue(legacy.last_synced_hash)  # baseline adopted

            # A genuine remote edit after baseline adoption does apply.
            calls["remote_records"]["tbl_responses"][0]["fields"]["教师批注"] = "第二次编辑"
            result = await syncer.pull_course(db, course_id)
            self.assertEqual(result["tables"]["responses"]["updated"], 1)
            db.expire_all()
            resp = db.get(StudentResponse, resp.id)
            self.assertEqual(resp.teacher_note, "第二次编辑")
        finally:
            db.close()
            await http.aclose()

    async def test_pull_student_comment_draft(self):
        calls = {"create": [], "update": [], "remote_records": {}}
        client, http = _configured_client(calls)
        db = SessionLocal()
        try:
            course_id = self._seed_course(db)
            syncer = BitableSyncer(client)
            await syncer.sync_course(db, course_id)
            student = db.query(Student).filter(Student.course_id == course_id).first()
            binding = (
                db.query(FeishuBinding)
                .filter(
                    FeishuBinding.entity_type == "student",
                    FeishuBinding.entity_id == student.id,
                    FeishuBinding.table_key == "students",
                )
                .first()
            )
            calls["remote_records"]["tbl_students"] = [
                {"record_id": binding.remote_record_id, "fields": {"评语草稿": "表格写的新评语"}}
            ]
            result = await syncer.pull_course(db, course_id)
            self.assertEqual(result["tables"]["students"]["updated"], 1)
            db.expire_all()
            student = db.get(Student, student.id)
            self.assertEqual(student.comment_draft, "表格写的新评语")
        finally:
            db.close()
            await http.aclose()

    async def test_pull_unconfigured_is_safe(self):
        db = SessionLocal()
        try:
            course_id = self._seed_course(db)
            unconfigured = _unconfigured_client()
            try:
                syncer = BitableSyncer(unconfigured)
                result = await syncer.pull_course(db, course_id)
                self.assertFalse(result["configured"])
                self.assertEqual(result["mode"], "deferred")
            finally:
                await unconfigured._http.aclose()
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
