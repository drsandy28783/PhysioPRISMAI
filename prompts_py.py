def generate_history_questions_prompt(age_sex: str, present_history: str) -> str:
    return (
        "You are a physiotherapy clinical decision-support assistant. "
        "Exclude any patient identifiers.\n"
        "History provided:\n"
        f"- Age/Sex: {age_sex}\n"
        f"- Present history: {present_history}\n\n"
        "Provide five concise follow-up questions to clarify the patient's past medical history, "
        "focusing on relevant comorbidities, risk factors, and symptom timeline. "
        "Format as a numbered list."
    )

def generate_diagnosis_prompt(age_sex: str, present_history: str, past_history: str) -> str:
    return (
        "You are a physiotherapy clinical decision-support assistant. "
        "Exclude any patient identifiers.\n"
        "History provided:\n"
        f"- Age/Sex: {age_sex}\n"
        f"- Present history: {present_history}\n"
        f"- Past history: {past_history}\n\n"
        "List up to two possible provisional diagnoses with a one-sentence rationale each. "
        "Format each as a numbered item."
    )

def generate_subjective_field_prompt(age_sex: str, present_history: str, past_history: str, inputs: dict, field: str) -> str:
    subjective_lines = "\n".join(
        f"- {k.replace('_', ' ').title()}: {v}"
        for k, v in inputs.items()
        if k != field and v
    )
    return (
        "You're a physiotherapy clinical decision-support assistant. Exclude all identifiers.\n"
        "Patient info:\n"
        f"- Age/Sex: {age_sex}\n"
        f"- Present history: {present_history}\n"
        f"- Past history: {past_history}\n\n"
        "Subjective findings so far:\n"
        f"{subjective_lines}\n\n"
        f"For **{field.replace('_', ' ').title()}**, provide **2 – 3 concise, open-ended questions** to explore this area further (align with WHO ICF)."
    )


def generate_subjective_diagnosis_prompt(age_sex: str, present_history: str, past_history: str, inputs: dict) -> str:
    findings = "\n".join(
        f"- {k.replace('_', ' ').title()}: {v}"
        for k, v in inputs.items()
        if v
    )
    return (
        "You're a physiotherapy clinical decision-support assistant. Exclude all identifiers.\n"
        "Patient info:\n"
        f"- Age/Sex: {age_sex}\n"
        f"- Present history: {present_history}\n"
        f"- Past history: {past_history}\n\n"
        "Subjective exam findings:\n"
        f"{findings}\n\n"
        "List up to **2 provisional diagnoses** with a **one-sentence rationale** each. Format as a numbered list."
    )

def generate_perspectives_field_prompt(previous, inputs, field):
    age_sex = previous.get('age_sex', '')
    present = previous.get('present_history', '')
    past = previous.get('past_history', '')
    subj = previous.get('subjective', {})
    perspectives = previous.get('perspectives', {})

    prompt = (
        "You are a physiotherapy clinical decision-support assistant. Exclude any identifiers.\n"
        "Patient summary:\n"
        f"- Age/Sex: {age_sex}\n"
        f"- Present history: {present}\n"
        f"- Past history: {past}\n\n"
        "Subjective findings:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in subj.items() if v) +
        "\n\nPatient perspectives recorded so far:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in perspectives.items() if k != field and v) +
        f"\n\nFor **{field.replace('_', ' ').title()}**, suggest **2–3 concise, open-ended questions** a physiotherapist can ask to explore this area deeper. "
        "Format as a numbered list."
    )
    return prompt


def generate_perspectives_diagnosis_prompt(previous, inputs):
    age_sex = previous.get('age_sex', '')
    present = previous.get('present_history', '')
    past = previous.get('past_history', '')
    subj = previous.get('subjective', {})
    persps = inputs

    prompt = (
        "You are a physiotherapy clinical decision-support assistant. Exclude any identifiers.\n"
        "Patient summary:\n"
        f"- Age/Sex: {age_sex}\n"
        f"- Present history: {present}\n"
        f"- Past history: {past}\n\n"
        "Subjective findings:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in subj.items() if v) +
        "\n\nPatient perspectives:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in persps.items() if v) +
        "\nProvide up to **2 provisional clinical impressions** (**1–2 sentences each**), integrating these perspectives. "
        "Number each item."
    )
    return prompt

def generate_initial_plan_prompt(prev, field, selection):
    prompt = (
        "You are a PHI-safe clinical assessment assistant. Use WHO-ICF and physiotherapy best practices.\n\n"
        "Patient context:\n"
        f"- Age/Sex: {prev.get('age_sex', '')}\n"
        f"- Present history: {prev.get('present_history', '')}\n"
        f"- Past history: {prev.get('past_history', '')}\n\n"
        "Subjective findings:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in prev.get('subjective', {}).items() if v) +
        "\n\nPerspectives:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in prev.get('perspectives', {}).items() if v) +
        f"\n\nThe therapist marked **{field.replace('_', ' ').title()}** as **{selection}**. "
        "Interpret **Mandatory assessment** as essential tests, **Assessment with precaution** as tests requiring caution, "
        "and **Absolutely Contraindicated** as tests to avoid. "
        "List **2-4** specific tests or maneuvers matching this category as a bullet list."
    )
    return prompt


def generate_initial_plan_summary_prompt(prev, assessments):
    prompt = (
        "You are a PHI-safe clinical summarizer.\n\n"
        "Patient context:\n"
        f"- Age/Sex: {prev.get('age_sex', '')}\n"
        f"- Present history: {prev.get('present_history', '')}\n"
        f"- Past history: {prev.get('past_history', '')}\n\n"
        "Subjective findings:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in prev.get('subjective', {}).items() if v) +
        "\n\nPerspectives:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in prev.get('perspectives', {}).items() if v) +
        "\n\nAssessment plan:\n" +
        "\n".join(
            f"- {k.replace('_', ' ').title()}: {assessments[k]['choice']} ({assessments[k]['details']})"
            for k in assessments
        ) +
        "\n\nProvide a concise 2-3 sentence summary of the assessment findings and up to two provisional diagnoses."
    )
    return prompt

def generate_patho_possible_source_prompt(prev, selection):
    prompt = (
        "You are a PHI-safe clinical reasoning assistant. Integrate all collected patient data: "
        "demographics, presenting complaint, medical history, subjective findings, "
        "patient perspectives, and planned assessments.\n\n"
        "Patient summary:\n"
        f"- Age/Sex: {prev.get('age_sex', '')}\n"
        f"- Present history: {prev.get('present_history', '')}\n"
        f"- Past history: {prev.get('past_history', '')}\n\n"
        "Subjective findings:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in prev.get('subjective', {}).items() if v) +
        "\n\nPerspectives:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in prev.get('perspectives', {}).items() if v) +
        "\n\nAssessment plan:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in prev.get('assessments', {}).items() if v and v.get('choice')) +
        f"\n\nThe clinician marked **Possible Source of Symptoms** as **{selection}**. "
        "Describe 2-3 concise, plausible anatomical or physiological mechanisms explaining how this source produces the patient's symptoms. "
        "Format as a numbered list."
    )
    return prompt

def generate_chronic_factors_prompt(prev, text_input, causes_selected):
    causes_text = (
        "\n".join(f"- {c}" for c in causes_selected) if causes_selected else "- None"
    )

    prompt = (
        "You are a PHI-safe clinical questioning assistant. Integrate all prior patient data:\n"
        f"- Age/Sex: {prev.get('age_sex', '')}\n"
        f"- Present history: {prev.get('present_history', '')}\n"
        f"- Past history: {prev.get('past_history', '')}\n\n"
        "Subjective findings:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in prev.get('subjective', {}).items() if v) +
        "\n\nPerspectives:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v}" for k, v in prev.get('perspectives', {}).items() if v) +
        "\n\nAssessment plan:\n" +
        "\n".join(f"- {k.replace('_', ' ').title()}: {v.get('choice')}" for k, v in prev.get('assessments', {}).items() if v.get('choice')) +
        "\n\nThe clinician indicated these maintenance causes:\n" + causes_text +
        f"\n\nSpecific factors described: {text_input}\n\n"
        "What 3-5 directed, open-ended questions should the physiotherapist ask to clarify these chronic contributing factors?"
    )
    return prompt

def generate_clinical_flags_prompt(prev, field, text):
    relevancy_hints = []
    if prev.get('subjective', {}).get('pain_irritability') == 'Present':
        relevancy_hints.append("Psychosocial risk factors (Yellow Flags)")
    if prev.get('assessments', {}).get('special_tests', {}).get('choice') == 'Absolutely Contraindicated':
        relevancy_hints.append("System/Environment barriers (Black Flags)")

    prompt = (
        "You are a PHI-safe clinical prompting assistant.\n"
        "Integrate patient data:\n"
        f"- Age/Sex: {prev.get('age_sex', '')}\n"
        f"- Present history: {prev.get('present_history', '')}\n"
        f"- Past history: {prev.get('past_history', '')}\n\n"
        "Subjective findings:\n"
        + "\n".join(f"- {k.title()}: {v}" for k, v in prev.get('subjective', {}).items() if v) +
        "\n\nPerspectives:\n"
        + "\n".join(f"- {k.title()}: {v}" for k, v in prev.get('perspectives', {}).items() if v) +
        "\n\nAssessments:\n"
        + "\n".join(f"- {k.title()}: {v.get('choice')}" for k, v in prev.get('assessments', {}).items() if v.get('choice')) +
        "\n\nRelevant flags to consider (based on above):\n"
        + "\n".join(f"- {h}" for h in relevancy_hints or ["- General flags"]) +
        f"\n\nYou are focusing on **{field.replace('_', ' ').title()}** where the clinician noted:\n{text}\n\n"
        "List 3–5 open-ended follow-up questions a physiotherapist should ask to probe this flag."
    )
    return prompt

def generate_objective_assessment_prompt(patient_id, field, choice):
    prompt = (
        f"A physio is filling out an objective assessment for patient {patient_id}. "
        f"They have chosen '{choice}' for the '{field}' field. "
        "List 3–5 specific assessments they should perform next."
    )
    return prompt

def generate_objective_field_prompt(patient_id, field, choice):
    prompt = (
        f"A physiotherapist is filling out an objective assessment for patient {patient_id}. "
        f"They have chosen '{choice}' for the '{field}' field. "
        "List 3–5 specific assessments they should perform next."
    )
    return prompt


def generate_provisional_diagnosis_prompt(patient_id, field, patient):
    prompts = {
        'likelihood': f"Given all prior data for patient {patient_id}, suggest how likely diagnoses should be phrased.",
        'structure_fault': f"For patient {patient_id}, suggest which anatomical structures to consider faulty based on history.",
        'symptom': f"For patient {patient_id}, suggest clarifying questions about their main symptom.",
        'findings_support': f"List clinical findings that would support the provisional diagnosis in patient {patient_id}.",
        'findings_reject': f"List common findings that might rule out this provisional diagnosis for patient {patient_id}."
    }

    prompt = prompts.get(field, f"Help with '{field}' for patient {patient_id}.")
    return prompt



def generate_smart_goals_prompt(field, prev, text):
    prompts = {
        'patient_goal': "Based on the patient’s entire record, suggest 2–3 patient-centric SMART goals they could aim for.",
        'baseline_status': "Given those goals and the patient context, what baseline status should I record? Describe the starting point.",
        'measurable_outcome': "What measurable outcomes would you expect for these goals? List 2–3 concrete metrics.",
        'time_duration': "What realistic time duration (e.g. weeks or months) fits those outcomes given the patient's condition?"
    }

    base_prompt = prompts.get(field, f"You are a PHI-safe physiotherapy assistant. Help with field '{field}'.")

    context_lines = []
    for k, v in prev.items():
        if v:
            context_lines.append(f"- {k}: {v}")
    if context_lines:
        base_prompt += "\n\nPatient context:\n" + "\n".join(context_lines)

    if text:
        base_prompt += f"\n\nCurrent input: {text}"

    return base_prompt

def generate_treatment_plan_prompt(field, text_input):
    prompts = {
        'treatment_plan': "Based on this patient's case, outline 3–4 evidence-based interventions you would include in the treatment plan.",
        'goal_targeted': "Given the treatment goals and patient context, what specific goal would you target first?",
        'reasoning': "Explain the clinical reasoning that links the chosen interventions to the patient’s impairments.",
        'reference': "Suggest 1–2 key references (articles or guidelines) that support this plan."
    }

    prompt = prompts.get(
        field,
        f"For the field '{field}', provide a brief suggestion based on the patient's data."
    )

    if text_input:
        prompt += f"\n\nCurrent input: {text_input}"

    return prompt


def generate_treatment_summary_prompt(patient_info, subj, persp, assess, patho, chronic, flags, objective, prov_dx, goals, tx_plan):
    prompt = (
        "You are a PHI-safe clinical summarization assistant.\n\n"
        f"Patient demographics: {patient_info.get('age_sex', 'N/A')}; "
        f"Sex: {patient_info.get('sex', 'N/A')}.\n"
        f"Past medical history: {patient_info.get('past_history', 'N/A')}.\n\n"

        "Subjective examination:\n"
        + "\n".join(f"- {k}: {v}" for k, v in subj.items() if k not in ('patient_id', 'timestamp')) + "\n\n"

        "Patient perspectives (ICF model):\n"
        + "\n".join(f"- {k}: {v}" for k, v in persp.items() if k not in ('patient_id', 'timestamp')) + "\n\n"

        "Initial plan of assessment:\n"
        + "\n".join(
            f"- {k}: {v.get('choice')} (details: {v.get('details', '')})"
            for k, v in assess.items() if k not in ('patient_id', 'timestamp')
        ) + "\n\n"

        "Pathophysiological mechanism:\n"
        + "\n".join(f"- {k}: {v}" for k, v in patho.items() if k not in ('patient_id', 'timestamp')) + "\n\n"

        "Chronic disease factors:\n"
        f"- Maintenance causes: {chronic.get('maintenance_causes', '')}\n"
        f"- Specific factors: {chronic.get('specific_factors', '')}\n\n"

        "Clinical flags:\n"
        + "\n".join(f"- {k}: {v}" for k, v in flags.items() if k not in ('patient_id', 'timestamp')) + "\n\n"

        "Objective assessment:\n"
        + "\n".join(f"- {k}: {v}" for k, v in objective.items() if k not in ('patient_id', 'timestamp')) + "\n\n"

        "SMART goals:\n"
        + "\n".join(f"- {k}: {v}" for k, v in goals.items() if k not in ('patient_id', 'timestamp')) + "\n\n"

        "Finally, the treatment plan:\n"
        + "\n".join(f"- {k}: {v}" for k, v in tx_plan.items() if k not in ('patient_id', 'timestamp')) + "\n\n"

        "Using all of the above, create a **concise treatment plan summary** that links the patient's history, exam findings, goals, and interventions into a coherent paragraph."
    )
    return prompt

def generate_followup_prompt(patient, session_no, session_date, grade, perception, feedback, patient_id):
    case_summary_lines = [
        f"Age/Sex: {patient.get('age_sex', 'N/A')}",
        f"History: {patient.get('chief_complaint', '')}",
        f"Subjective: {patient.get('subjective_notes', '')}",
        f"Perspectives: {patient.get('perspectives_summary', '')}",
        f"Initial Plan: {patient.get('initial_plan_summary', '')}",
        f"SMART Goals: {patient.get('smart_goals_summary', '')}"
    ]
    case_summary = "\n".join(line for line in case_summary_lines if line.split(":", 1)[1])

    prompt = (
        "You are a PHI-safe clinical reasoning assistant for physiotherapy.\n\n"
        f"Patient ID: {patient_id}\n\n"
        "Case summary so far:\n"
        f"{case_summary}\n\n"
        "New follow-up session details:\n"
        f"🔁 Session #: {session_no} on {session_date}\n"
        f"🎯 Grade: {grade}\n"
        f"🧠 Perception: {perception}\n"
        f"💬 Feedback: {feedback}\n\n"
        "Based on ICF guidelines, the SMART Goals above, and the new session data, "
        "suggest a focused plan for the next treatment."
    )
    return prompt

