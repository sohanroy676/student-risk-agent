from pathlib import Path

import pytest

INFO = """code_module,code_presentation,id_student,gender,region,highest_education,imd_band,\
age_band,num_of_prev_attempts,studied_credits,disability,final_result
AAA,2013J,1,M,Wales,A Level,10-20%,0-35,0,60,N,Pass
AAA,2013J,2,F,Wales,A Level,10-20%,0-35,0,60,N,Withdrawn
AAA,2014J,1,M,Wales,A Level,10-20%,0-35,1,60,N,Fail
BBB,2013J,3,F,Kent,HE,?,35-55,0,60,Y,Distinction
AAA,2013J,1,M,Wales,A Level,10-20%,0-35,0,60,N,Pass
"""
COURSES = """code_module,code_presentation,module_presentation_length
AAA,2013J,268
AAA,2014J,269
BBB,2013J,240
"""
ASSESSMENTS = """code_module,code_presentation,id_assessment,assessment_type,date,weight
AAA,2013J,10,TMA,19,10
AAA,2013J,11,Exam,,100
AAA,2014J,12,TMA,19,10
"""
STUDENT_ASSESSMENT = """id_assessment,id_student,date_submitted,is_banked,score
10,1,18,0,80
10,2,25,0,
11,1,260,0,70
10,1,18,1,99
12,1,20,0,50
"""
VLE = """code_module,code_presentation,id_student,id_site,date,sum_click
AAA,2013J,1,500,-5,3
AAA,2013J,1,501,0,2
AAA,2014J,1,500,7,4
BBB,2013J,3,502,1,1
"""


@pytest.fixture
def oulad_dir(tmp_path: Path) -> Path:
    files = {
        "studentInfo.csv": INFO,
        "courses.csv": COURSES,
        "assessments.csv": ASSESSMENTS,
        "studentAssessment.csv": STUDENT_ASSESSMENT,
        "studentVle.csv": VLE,
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return tmp_path
