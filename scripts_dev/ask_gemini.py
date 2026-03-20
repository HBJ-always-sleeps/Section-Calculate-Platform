import sys
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

def analyze_and_fix(error_text):
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    # 使用 Gemini 2.0 Flash，速度快且逻辑强
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    sys_prompt = """
    你是一个中望CAD自动化专家。
    刚才 Cline 在执行任务时报错了。
    请分析报错原因，并给出一行 Aider 指令来修复它。
    指令格式必须是：aider --model qwen3-coder-plus --message "你的修复指令"
    """
    
    response = model.generate_content(f"{sys_prompt}\n\n报错内容：\n{error_text}")
    return response.text

if __name__ == "__main__":
    error_input = sys.argv[1] if len(sys.argv) > 1 else "Unknown Error"
    result = analyze_and_fix(error_input)
    
    # 写入 REMEDY.md 供 Cline 读取
    with open("REMEDY.md", "w", encoding="utf-8") as f:
        f.write(result)
    
    print(f"Gemini 已开出药方，详见 REMEDY.md")