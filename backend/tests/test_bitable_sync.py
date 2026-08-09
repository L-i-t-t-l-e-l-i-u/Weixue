import json
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace

# Isolate the database before importing the models.
_TMP_DIR = tempfile.mkdtemp(prefix="weixue_bitable_test_")
os.environ["WEIXUE_DB_PATH"] = os.path.join(_TMP_DIR, "test.db")

import httpx

from database import (
    Course,
    DebateTopic,
    FeishuBinding,
    Student,
    StudentResponse,
    SessionLocal,
    init_db,
)
from feishu.client import FeishuClient, FeishuConfig
from feishu.sync import (
    BitableSyncer,
    bitable_is_configured,
    bitable_status,
    build_course_record,
    build_response_record,
    build_student_record,
    build_topic_record,
)


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
        self.assertEqual(fields["类型"], {"text": "两难"})
        self.assertEqual(fields["认知梯段"], {"text": "发展层"})
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
        self.assertEqual(fields["认知梯段"], {"text": "基础层"})
        self.assertEqual(fields["班级"], "思辨一班")

    def test_response_record_status_and_multi_select(self):
        response = SimpleNamespace(
            teacher_reviewed=True,
            ai_dimension_scores={"clarity": "A", "relevance": "B+"},
            ai_confidence="certain_good",
            ai_suggested_tags=["因果推理", "证据意识"],
            teacher_dimension_scores={"clarity": "A"},
            teacher_tags=["证据意识"],
            teacher_note="表达流畅",
            raw_text="原文",
            cleaned_text="清洗稿",
            source="asr",
        )
        student = SimpleNamespace(name="小雨")
        topic = SimpleNamespace(title="动物应该养在动物园吗？")
        fields = build_response_record(response, student, topic)["fields"]
        self.assertEqual(fields["学生"], "小雨")
        self.assertEqual(fields["来源"], {"text": "音频转写"})
        self.assertEqual(fields["AI置信度"], {"text": "高"})
        self.assertEqual(fields["状态"], {"text": "教师已审"})
        self.assertEqual(fields["AI建议标签"], [{"text": "因果推理"}, {"text": "证据意识"}])
        self.assertIn("clarity:A", fields["AI评分摘要"])


class BitableSyncTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP_DIR, ignore_errors=True)

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
            ai_dimension_scores={"clarity": "A"},
            ai_confidence="uncertain",
            ai_suggested_tags=["因果推理"],
            teacher_reviewed=True,
            teacher_dimension_scores={"clarity": "A"},
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


if __name__ == "__main__":
    unittest.main()
