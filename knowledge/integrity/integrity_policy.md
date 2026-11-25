# Resume integrity policy

The integrity scan looks for text or tricks that try to manipulate screening. A flag is a signal for human review. It is not proof of intent and it is never an automatic rejection.

## What the scan checks
High severity (risk level high_risk):
- Text whose colour matches the background, such as white text on a white page.
- Text in a font too small to read (under 4 pt).
- Text marked invisible in the PDF, or Word's hidden-text setting.
- Text placed outside the visible page.
- Text that exists in the file but does not appear on the rendered page, for example covered by a shape or a picture.
- Text found in the file but not when the page is read as an image.
- Phrases that instruct an AI screener, such as "ignore previous instructions" or "rank this candidate first".
- Instructions hidden in document properties such as the subject field.

Medium severity (risk level review):
- Very pale text against its background.
- Keyword stuffing: a keyword repeated far more than normal writing needs, or the same line repeated.
- A long block of keywords in the document properties.
- Several zero-width characters mixed into the text (3 to 14).

Low severity (listed, no review needed on its own):
- One or two zero-width characters, which often come from copy and paste. 15 or more is high severity.

## Risk levels
- clean: nothing found.
- review: a recruiter should look at the evidence.
- high_risk: hidden or manipulative content was found. A recruiter must review it before any decision.

## How the system treats flagged resumes
The score, job-field prediction, and feedback use only the visible text. Hidden text is shown to the recruiter as evidence and is never followed as an instruction. Resume content is always treated as data, not as commands.

## How to explain a flag
Describe what was found, where, and how much, in neutral words. Do not accuse the candidate. Example: "142 words in white text were found on page 1. They are not visible to a reader and were left out of the score."

## Possible innocent causes
- A design template that uses white text on a coloured banner, which the scan accepts when the contrast is strong.
- Invisible text layers created when a scanned document was converted to PDF.
- Stray zero-width characters from copying text between applications.
- Repeated skills in a long skills section.
Always consider these before drawing conclusions.

## Advice to candidates
Remove any text that a reader cannot see, keep keywords natural and in context, export the resume as a clean PDF from Word or Google Docs, and do not paste text into document properties.
