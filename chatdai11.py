import streamlit as st
import base64
from openai import OpenAI
import httpx
import json
import io
import os
import time
from urllib.parse import urlparse
from streamlit_mic_recorder import mic_recorder

# إعداد الصفحة وتغيير الاسم إلى ai chat وتفعيل اتجاه الـ RTL للنصوص العربية
st.set_page_config(page_title="ai chat", layout="wide")

st.markdown(
    """
    <style>
    .stApp {
        direction: ltr;
        text-align: left;
    }
    .stChatMessage {
        text-align: left;
    }
    /* تثبيت خانة الإدخال في أسفل الصفحة تماماً */
    div[data-testid="stVerticalBlock"] div:has(> div.fixed-bottom-container) {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        z-index: 99999;
    }
    .fixed-bottom-container {
        background-color: #0e1117;
        padding: 12px 20px;
        border-top: 1px solid #262730;
        width: 100%;
    }
    .block-container {
        padding-bottom: 120px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

try:
    import pypdf
except ImportError:
    pypdf = None

GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=GOOGLE_API_KEY,
)

SELECTED_MODEL = "gemini-3.5-flash-lite"

def safe_chat_completion(client_obj, model_name, messages, temperature=0.3, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = client_obj.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature
            )
            return response
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    wait_time = 20 * (attempt + 1)
                    st.warning(f"⚠️ تم الوصول للحد الأقصى المؤقت للطلبات. جاري إعادة المحاولة خلال {wait_time} ثانية...")
                    time.sleep(wait_time)
                    continue
            raise e
    raise Exception("فشلت جميع محاولات الاتصال بسبب استنزاف الحصة المسموحة.")

default_source_type = "Private API (with Token)"
default_url = "http://192.168.30.131:56/swagger/v1/swagger.json"
default_token = ""
default_db_conn = "Data Source=(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=192.168.30.133)(PORT=1521))(CONNECT_DATA=(SERVER=DEDICATED)(SID=etech19c)));User Id=zagelabnewtest;Password=zagelabnewtest;"

CONFIG_FILE_PATH = "config.json"

if 'config_loaded' not in st.session_state:
    st.session_state['config_loaded'] = False
    databases_conf = {}
    
    loaded_source_type = default_source_type
    loaded_url = default_url
    loaded_token = default_token
    loaded_db_conn = default_db_conn

    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                loaded_source_type = config_data.get("default_source_type", default_source_type)
                api_conf = config_data.get("api", {})
                loaded_url = api_conf.get("source_url", default_url)
                loaded_token = api_conf.get("token", default_token)
                databases_conf = config_data.get("databases", {})
                if loaded_source_type in databases_conf:
                    loaded_db_conn = databases_conf[loaded_source_type]
        except Exception as e:
            st.sidebar.error(f"خطأ في قراءة ملف config.json: {str(e)}")
    
    st.session_state['source_type'] = loaded_source_type
    st.session_state['source_url'] = loaded_url
    st.session_state['token_input'] = loaded_token
    st.session_state['db_conn_string'] = loaded_db_conn
    st.session_state['databases_config'] = databases_conf
    st.session_state['config_loaded'] = True

    try:
        if "Database" not in loaded_source_type and loaded_url:
            headers = {"User-Agent": "Mozilla/5.0"}
            if loaded_token:
                headers["Authorization"] = loaded_token if loaded_token.startswith("Bearer ") else f"Bearer {loaded_token}"
            
            response = httpx.get(loaded_url, timeout=20, verify=False, follow_redirects=True, headers=headers)
            if response.status_code == 200:
                try:
                    swagger_data = response.json()
                except Exception:
                    swagger_data = {"paths": {}, "info": {"title": "Raw HTML/Text Response"}}
                    
                endpoints_dict = {}
                if isinstance(swagger_data, dict):
                    paths = swagger_data.get("paths", {})
                    for path, methods in paths.items():
                        for method, details in methods.items():
                            tags = details.get("tags", ["Other"])
                            summary = details.get("summary", "")
                            endpoints_dict[path] = {
                                "method": method.upper(),
                                "tags": tags,
                                "summary": summary
                            }
                st.session_state['swagger_raw'] = swagger_data
                st.session_state['endpoints_dict'] = endpoints_dict
    except Exception:
        pass

# --- الشريط الجانبي (Sidebar) للملفات، الصور، والتسجيل الصوتي ---
with st.sidebar:
    st.markdown("### 📁 مرفقات الملفات والصوتيات والصور")
    st.write("أو صوت، Screenshot/صورة، ملف (PDF) رفع ملف (TXT, PDF, PNG, JPG, ...):")
    
    uploaded_file = st.file_uploader(
        "رفع ملف (PDF، نصي، CSV...):", 
        type=["txt", "pdf", "csv", "json", "log"], 
        key="sidebar_file_uploader"
    )
    
    chat_image_file = st.file_uploader(
        "إرفاق صورة أو لقطة شاشة (Screenshot):", 
        type=["png", "jpg", "jpeg", "webp"], 
        key="sidebar_image_uploader"
    )
    
    st.markdown("---")
    st.markdown("### 🎙️ التسجيل الصوتي")
    audio_data = mic_recorder(start_prompt="🎙️ بدء التسجيل", stop_prompt="⏹️ إيقاف التسجيل", key='mic')
    
    st.markdown("---")
    selected_model_dropdown = st.selectbox(
        "اختر نموذج الذكاء الاصطناعي",
        ["Flash-Lite", "Flash 1.5", "Pro"]
    )

st.title("🤖 ai chat - المساعد الذكي الشامل")
st.write("اسأل عن بيانات النظام أو ارفع الملفات من القائمة الجانبية!")

if "messages" not in st.session_state:
    st.session_state.messages = []

# عرض المحادثات السابقة
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("image_bytes"):
            st.image(message["image_bytes"], caption="الصورة المرفقة", use_container_width=True)
        st.markdown(message["content"])

user_prompt = None
document_content = ""
image_to_process = None

# شريط الإدخال السفلي للشات فقط
st.markdown('<div class="fixed-bottom-container">', unsafe_allow_html=True)
chat_input_text = st.chat_input("اكتب سؤالك أو استفسارك هنا...")
st.markdown('</div>', unsafe_allow_html=True)

# التحقق من الملفات المرفوعة من الـ Sidebar
if chat_image_file is not None:
    image_to_process = chat_image_file.getvalue()

if uploaded_file is not None:
    try:
        file_bytes = uploaded_file.getvalue()
        file_extension = uploaded_file.name.split('.')[-1].lower()
        if file_extension in ["txt", "csv", "json", "log"]:
            document_content = file_bytes.decode("utf-8", errors="ignore")
        elif file_extension == "pdf" and pypdf:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    document_content += text + "\n"
    except Exception as ex:
        st.error(f"خطأ في معالجة الملف: {str(ex)}")

# معالجة الصورة أو الـ Screenshot المرفقة من الـ Sidebar
if image_to_process is not None:
    try:
        base64_image = base64.b64encode(image_to_process).decode('utf-8')
        vision_response = client.chat.completions.create(
            model=SELECTED_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "قم بقراءة واستخراج كافة النصوص والأرقام والمحتوى الموجود في هذه الصورة أو لقطة الشاشة بدقة شديدة."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }],
            max_tokens=1500
        )
        extracted_img_text = vision_response.choices[0].message.content.strip()
        document_content += f"\n\nمحتوى الصورة المستخرج:\n{extracted_img_text}"
        if not user_prompt:
            user_prompt = "قم بتحليل هذه الصورة أو لقطة الشاشة واستخرج المعلومات المهمة منها."
    except Exception as img_err:
        st.error(f"خطأ في تحليل الصورة: {str(img_err)}")

if chat_input_text:
    user_prompt = chat_input_text

# معالجة التسجيل الصوتي من الـ Sidebar
if audio_data:
    try:
        with st.spinner("🎙️ جاري تفريغ الصوت عبر Whisper..."):
            audio_bytes = audio_data['bytes']
            audio_file_obj = ("voice_input.wav", audio_bytes, "audio/wav")
            transcript_response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file_obj
            )
            user_prompt = transcript_response.text
            st.success(f"✅ النص المنطوق: {user_prompt}")
    except Exception as mic_err:
        st.error(f"خطأ في معالجة التسجيل الصوتي: {str(mic_err)}")

if uploaded_file and not user_prompt and not image_to_process:
    user_prompt = "قم بتحليل هذا المستند المرفق، ولخص محتواه، واستخرج كافة المعلومات المفيدة منه."

if user_prompt:
    message_entry = {"role": "user", "content": user_prompt}
    if image_to_process:
        message_entry["image_bytes"] = image_to_process
    
    st.session_state.messages.append(message_entry)
    with st.chat_message("user"):
        if image_to_process:
            st.image(image_to_process, caption="الصورة المرفقة", use_container_width=True)
        st.markdown(user_prompt)

    source_type = st.session_state.get('source_type', '')
    has_swagger = 'endpoints_dict' in st.session_state and "Database" not in source_type

    endpoints_summary_list = []
    if has_swagger:
        for path, details in st.session_state['endpoints_dict'].items():
            endpoints_summary_list.append(f"Path: {path} | Method: {details['method']} | Summary: {details['summary']}")

    swagger_json_str = json.dumps(endpoints_summary_list[:250], ensure_ascii=False) if has_swagger else "لا توجد مسارات محملة."
    doc_text_section = f"نص المستند أو محتوى الصورة المستخرج:\n{document_content}" if document_content else ""

    planning_prompt = f"""
أنت مساعد تقني ذكي جداً لتحليل طلبات المستخدمين ومطابقتها مع مسارات الـ API (Endpoints) المتاحة في الـ Swagger.
رابط السيرفر الأساسي: {st.session_state.get('source_url', '')}
قائمة مسارات الـ API المتاحة وطرق استدعائها:
{swagger_json_str}

سؤال أو طلب المستخدم الشامل: "{user_prompt}"
{doc_text_section}

مهمتك:
1. قم بتحليل سؤال المستخدم بدقة واختر المسار (Path) الأكثر ملاءمة من القائمة أعلاه (سواء كان Public أو Private API).
2. حدد طريقة الطلب الصحيحة تماماً (GET أو POST) وضعها في الحقل `method_1`.
3. إذا كان الطلب POST ويحتاج لبيانات مرسلة في الـ Body بناءً على السؤال، ضعها في الحقل `body` (وإن لم يحتاج اجعله كائناً فارغاً {{}}).
4. ضع قيمة `needs_api` بـ `true` طالما وجد مسار مناسب لخدمة طلب المستخدم.
أجب بصيغة JSON حصراً بهذا الشكل ودون أي نصوص إضافية:
{{"needs_api": true, "path_1": "/api/PathFoundInSwagger", "method_1": "POST", "body": {{}}}}
"""

    with st.chat_message("assistant"):
        with st.spinner("جاري تحليل الطلب والاتصال بالـ API..."):
            try:
                plan_response = safe_chat_completion(
                    client,
                    SELECTED_MODEL,
                    [{"role": "user", "content": planning_prompt}],
                    temperature=0.1
                )
                
                plan_json_text = plan_response.choices[0].message.content.strip()
                if "```json" in plan_json_text:
                    plan_json_text = plan_json_text.split("```json")[1].split("```")[0].strip()
                elif "```" in plan_json_text:
                    plan_json_text = plan_json_text.split("```")[1].split("```")[0].strip()
                    
                plan_data = json.loads(plan_json_text)
                execution_result_text = None

                if has_swagger and plan_data.get("needs_api"):
                    req_headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
                    active_token = st.session_state.get('token_input', '')
                    if active_token:
                        req_headers["Authorization"] = active_token if active_token.startswith("Bearer ") else f"Bearer {active_token}"

                    path_1 = plan_data.get("path_1") or st.session_state.get('source_url', '')
                    if not path_1.startswith("http"):
                        parsed_url = urlparse(st.session_state.get('source_url', ''))
                        base_server_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                        raw_data = st.session_state.get('swagger_raw', {})
                        base_path = raw_data.get('basePath', '') if isinstance(raw_data, dict) else ''
                        full_url_1 = base_server_url + base_path + path_1
                    else:
                        full_url_1 = path_1
                        
                    req_method = plan_data.get("method_1", "GET").upper()
                    request_body = plan_data.get("body", {})
                    
                    try:
                        if req_method == "POST":
                            resp = httpx.post(full_url_1, headers=req_headers, json=request_body, timeout=15, verify=False)
                        else:
                            resp = httpx.get(full_url_1, headers=req_headers, timeout=15, verify=False)
                    except Exception as req_err:
                        resp = None
                        st.error(f"خطأ في الاتصال بالـ API: {str(req_err)}")

                    if resp is not None:
                        if resp.status_code == 200:
                            execution_result_text = resp.text.strip()
                        else:
                            execution_result_text = f"فشل الاستعلام وحالة الـ Response هي: {resp.status_code} - تفاصيل الخطأ: {resp.text}"
                    else:
                        execution_result_text = "تعذر الاتصال بالخادم."

                safe_result = execution_result_text[:4000] if execution_result_text else "لم يتم جلب بيانات."
                res_section = f"البيانات الفعلية المسترجعة من الـ API:\n{safe_result}" if execution_result_text else ""
                
                final_prompt = f"""
أنت مساعد ذكي ومحترف لتحليل البيانات وعرض الإجابات للمستخدمين.
سؤال أو طلب المستخدم: "{user_prompt}"
{doc_text_section}
{res_section}

مهمتك هي تقديم إجابة شاملة ومنظمة باللغة العربية:
1. قم بتحليل النتائج أو البيانات المسترجعة من الـ API بدقة وربطها بسؤال المستخدم.
2. اعرض البيانات بشكل منسق وواحداً تلو الآخر (جداول أو نقاط واضحة).
3. قدم خلاصة أو إجابة شافية ومباشرة تلبي طلب المستخدم تماماً.
"""

                final_response = safe_chat_completion(
                    client,
                    SELECTED_MODEL,
                    [{"role": "user", "content": final_prompt}],
                    temperature=0.3
                )
                
                final_answer = final_response.choices[0].message.content.strip()
                st.markdown(final_answer)
                st.session_state.messages.append({"role": "assistant", "content": final_answer})

            except Exception as e:
                error_msg = f"❌ حدث خطأ أثناء المعالجة: {str(e)}"
                st.markdown(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
