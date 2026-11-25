# run first: python Ingestion.py --dry-run (nothing so upload on vectordatabase just for check all records are working properly)
# run second: python Ingestion.py  (Send/upload records to vectore store (Pinecone))

import argparse
import hashlib
import os 
import re 
import sys
import time 
import pandas as pd 
import pymupdf
from langchain_core.documents import Document
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_pinecone import PineconeEmbeddings, PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec
import warnings
warnings.filterwarnings('ignore')
import os 
import time 
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
DATA_PATH = BASE / 'docs'
KNOWLEDGE_PATH = BASE / 'knowledge' 

INDEX_NAME = 'ats-knowledge'
NAMESPACE = 'knowledge-base'
CLOUD, REGRION = 'aws', 'us-east-1'
EMBED_MODEL = 'llama-text-embed-v2'
EMBED_DIM = 1024
CHUNK_SIZE, CHUNK_OVERLAP = 1000, 150
BATCH_SIZE = 32
MAX_RETRIES = 3 


CODE_COL, TITLE_COL, DESC_COL = 'O*NET-SOC Code', 'Title', 'Description'
TOOL_COL = 'Workplace Example'
TASK_COL = 'Task'
MAX_TOOLS, MAX_TASKS = 60, 15 
ONET_SOURCE = 'O*NET 30.3 Database (CC BY 4.0)'

ROLE_KEYWORDS = {
    'Data Scientist': ['Data Scientists'],
    'Data Analyst': ["Business Intelligence Analysts", "Operations Research Analysts"],
    'ML Engineer': ["Computer and Information Research Scientists"],
    'Software Developer': ["Software Developers"],
    'Web Developer': ["Web Developers"],
    'DevOps Engineer' : ["Network and Computer Systems Administrators", "Computer Network Architects"],
    'HR Executive' : ["Human Resources Specialists"],
    'Accountant' : ["Accountants and Auditors"],
    'Digital Marketing Executive': ["Market Research Analysts and Marketing Specialists"]
}

load_dotenv()

def find_csv(*words):
    for file in sorted(DATA_PATH.glob("*.csv")):
        if all(w in file.stem.lower() for w in words):
            return file 
    return None 

def read_csv(file, needed):
    df = pd.read_csv(file, encoding='utf-8-sig')
    missing = [c for c in needed if c not in df.columns]
    if missing:
        sys.exit(f"{file.name}: columns {missing} not found. Columns are: {list(df.columns)}. Edit the column settings at the top.")
    return df 

def unique_values(series, limit):
    return list(dict.fromkeys(series.dropna().astype(str)))[:limit]

def load_onet_documents():
    occ_file, tools_file, tasks_file = find_csv("occupation_data"), find_csv("software_skills"), find_csv('task_statements')
    if occ_file is None:
        print(f"[O*NET] 'Occupation Data' CSV not found in {DATA_PATH}; it is needed to get job titles. Skipping O*NET.")
        return [] 
    occ = read_csv(occ_file, [CODE_COL, TITLE_COL, DESC_COL])

    matches = [] 
    for role, phrases in ROLE_KEYWORDS.items():
        pattern = "|".join(re.escape(p) for p in phrases)
        hit = occ[occ[TITLE_COL].str.contains(pattern, case = False, regex = True)].copy()
        hit['role'] = role 
        matches.append(hit)
    matched = pd.concat(matches).drop_duplicates(subset = [CODE_COL, 'role'])
    print("[O*NET] matched occpations (check these):")
    print(matched[['role', CODE_COL, TITLE_COL]].to_string(index = False))

    df = matched
    if tools_file is not None:
        tools = read_csv(tools_file, [CODE_COL, TOOL_COL]).groupby(CODE_COL)[TOOL_COL].apply(
            lambda s:', '.join(unique_values(s, MAX_TOOLS))
        )
        df = df.merge(tools.rename("tools"), on = CODE_COL, how = 'left')
    if tasks_file is not None:
        tasks = read_csv(tasks_file, [CODE_COL, TASK_COL]).groupby(CODE_COL)[TASK_COL].apply(
            lambda s: "\n".join("- " + t for t in unique_values(s, MAX_TASKS))
        )
        df = df.merge(tasks.rename("tasks"), on = CODE_COL, how = 'left')
    for col in ('tools', 'tasks'):
        if col not in df.columns:
            df[col] = None 

    documents = []
    for _, row in df.iterrows():
        text = (
            f"Role: {row['role']}\nO*NET occupation: {row[TITLE_COL]}\nDescription: {row[DESC_COL]}\n"
            f"Common tools and software: {row['tools'] if pd.notna(row['tools']) else 'not listed'}\n"
            f"Typical tasks:\n{row['tasks'] if pd.notna(row['tasks']) else 'not listed'}"
        )
        documents.append(Document(page_content=text, metadata = {
            "doc_key": f"onet:{row[CODE_COL]}:{row['role']}", "role": row["role"], "onet_code": row[CODE_COL],
            "title": row[TITLE_COL], "topic": "role requirements", "source": ONET_SOURCE, "chunk_index": 0,

        }))
    return documents

def load_knowledge_documents():
    if not KNOWLEDGE_PATH.exists():
        print(f'[guides] folder not found: {KNOWLEDGE_PATH}. skipping guides.')
        return [] 
    documents = []
    for file in sorted(KNOWLEDGE_PATH.rglob("*")):
        if file.suffix.lower() not in {'.md', '.txt', '.pdf'}:
            continue
        rel = file.relative_to(KNOWLEDGE_PATH)
        role = rel.parts[1] if rel.parts[0] == 'roles' and len(rel.parts) > 2 else 'all'
        topic = rel.parts[0] if len(rel.parts) > 1 else 'general'
        base = {'source': rel.as_posix(), 'topic': topic, 'role': role}
        if file.suffix.lower() == '.pdf':
            with pymupdf.open(file) as pdf:
                for page_no, page in enumerate(pdf, start=1):
                    text = page.get_text().strip()
                    if text:
                        documents.append(Document(page_content=text, 
                        metadata = {**base, "doc_key": f"{rel.as_posix()} #p {page_no}" }))
        else:
            text = file.read_text(encoding='utf-8-sig', errors='ignore').strip()
            if text:
                documents.append(Document(page_content=text, metadata = {**base, 'doc_key': rel.as_posix()}))
    return documents 


# Creating chunks
def create_chunks(extracted_data):
    text_splitters = RecursiveCharacterTextSplitter(chunk_size = CHUNK_SIZE, chunk_overlap = CHUNK_OVERLAP)
    chunks = []
    for doc in extracted_data:
        for i, piece in enumerate(text_splitters.split_text(doc.page_content)):
            chunks.append(Document(page_content=piece, metadata = {**doc.metadata, 'chunk_index': i}))
    return chunks


# stable ids 
def make_id(doc):
    raw = f"{doc.metadata['doc_key']}|{doc.metadata['chunk_index']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


# Creating vector embeddings 
def vector_embeddings():
    return PineconeEmbeddings(model = EMBED_MODEL, dimension=EMBED_DIM)


def create_index(pc):
    if not pc.has_index(INDEX_NAME):
        pc.create_index(name = INDEX_NAME, dimension = EMBED_DIM, metric = 'cosine', 
                        spec = ServerlessSpec(cloud='aws', region='us-east-1'))
    while not pc.describe_index(INDEX_NAME).status['ready']:
        time.sleep(10)


def upload(vector_store, documents):
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i:i + BATCH_SIZE]
        ids = [make_id(d) for d in batch]
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                vector_store.add_documents(batch, ids = ids)
                break
            except Exception as exc:
                if attempt == MAX_RETRIES:
                    raise
                wait = 5 * 2 ** (attempt - 1)
                print(f"batch failed ({exc}); retrying in {wait}s")
                time.sleep(wait)
        print(f"Uploaded {min(i + BATCH_SIZE, len(documents))} / {len(documents)}")

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="load and chunk only (change 10)")
    ap.add_argument("--reset", action="store_true", help="empty the namespace before uploading (change 3)")
    args = ap.parse_args(argv)

    onet_docs = load_onet_documents()
    guide_chunks = create_chunks(load_knowledge_documents())
    documents = onet_docs + guide_chunks
    if not documents:
        sys.exit("Nothing to ingest. Check the docs/ and knowledge/ folders.")
    lengths = [len(d.page_content) for d in documents]
    print(f"\n{len(onet_docs)} O*NET documents + {len(guide_chunks)} guide chunks = {len(documents)} records "
          f"(average {sum(lengths) // len(lengths)} characters, longest {max(lengths)})")

    if args.dry_run:
        for d in onet_docs[:1] + guide_chunks[:1]:
            print("\n--- sample record ---\n", d.page_content[:400], "\n", d.metadata)
        print("\nDry run finished. Nothing was sent to Pinecone.")
        return

    
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        sys.exit("PINECONE_API_KEY is not set. Put it in your environment or a .env file.")
    pc = Pinecone(api_key=api_key)
    create_index(pc)
    if args.reset:
        try:
            pc.Index(INDEX_NAME).delete(delete_all=True, namespace=NAMESPACE)
        except Exception as exc:                                  # the namespace does not exist on a first run
            print(f"Reset skipped: {exc}")

    vector_store = PineconeVectorStore(index=pc.Index(INDEX_NAME), embedding=vector_embeddings(), namespace=NAMESPACE)
    upload(vector_store, documents)
    print("Vector database is created!")
    print(pc.Index(INDEX_NAME).describe_index_stats())


if __name__ == "__main__":
    main()









