from config import Settings
from engine import RagEngine

def get_rag_chain():
    engine = RagEngine(Settings.from_env())
    def answer(query):
        result = engine.ask('student', query.strip())
        return {"result": result["answer"], "source_documents": []}
    return answer
