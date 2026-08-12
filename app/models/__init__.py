"""集中导出所有 ORM Model，供应用和测试统一加载。"""

from app.models.job import Job
from app.models.job_analysis import JobAnalysis
from app.models.profile import CandidateProfile
from app.models.resume import Resume
from app.models.user import User

__all__ = ["CandidateProfile", "Job", "JobAnalysis", "Resume", "User"]
