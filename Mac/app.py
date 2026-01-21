import os
import json
import base64
import re
import platform
import subprocess
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from PIL import Image

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_FILE = os.path.join(BASE_DIR, 'database.json')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

def load_db():
    # 增加 remarks 字段用于存储备注
    default_db = {"categories": [], "cards": {}, "remarks": {}}
    if not os.path.exists(DB_FILE):
        return default_db
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if "categories" not in data: data["categories"] = []
            if "cards" not in data: data["cards"] = {}
            if "remarks" not in data: data["remarks"] = {}
            
            if "hidden_files" in data: del data["hidden_files"]
            if "默认" in data.get("categories", []):
                data["categories"].remove("默认")
            
            # === 关键修改：兼容性处理，把旧的 字符串分类 变成 列表分类 ===
            for k, v in data["cards"].items():
                if isinstance(v, str):
                    data["cards"][k] = [v] if v else []
            # =======================================================

            return data
    except:
        return default_db

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# === 清洗函数 ===
def smart_clean_text(text):
    if not text: return "暂无描述"
    s = str(text)
    s = re.sub(r'</?(info|character|character_information)[^>]*>', '', s, flags=re.IGNORECASE)
    s = s.replace('```yaml', '').replace('```', '')
    return s.strip()

def parse_card_metadata(filepath):
    filename = os.path.basename(filepath)
    data = { "name": filename, "description": "暂无描述", "first_mes": "", "alternate_greetings": [] }
    
    try:
        content = {}
        if filepath.endswith('.json'):
            with open(filepath, 'r', encoding='utf-8') as f: content = json.load(f)
        elif filepath.endswith('.png'):
            img = Image.open(filepath)
            img.load()
            chara_data = img.info.get('chara')
            if chara_data: content = json.loads(base64.b64decode(chara_data).decode('utf-8'))

        if content:
            target = content.get('data', content)
            raw_name = target.get('name', target.get('char_name', filename))
            data["name"] = raw_name.strip() if raw_name else filename
            
            raw_desc = target.get('description', target.get('char_persona', ''))
            cleaned_desc = smart_clean_text(raw_desc)
            data["description"] = cleaned_desc if cleaned_desc else "暂无描述"
            
            data["first_mes"] = smart_clean_text(target.get('first_mes', ''))
            
            raw_alts = target.get('alternate_greetings', [])
            if isinstance(raw_alts, list):
                data["alternate_greetings"] = [smart_clean_text(x) for x in raw_alts if smart_clean_text(x)]
                
    except Exception as e:
        print(f"解析错误 {filename}: {e}")
        
    return data

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    db = load_db()
    cards_list = []
    
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        # 按修改时间倒序排列
        files = sorted(os.listdir(app.config['UPLOAD_FOLDER']), 
                       key=lambda x: os.path.getmtime(os.path.join(app.config['UPLOAD_FOLDER'], x)), 
                       reverse=True)
        
        for filename in files:
            if filename.endswith(('.png', '.json')):
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                meta = parse_card_metadata(filepath)
                
                # === 修复开始：正确处理多分类列表 ===
                raw_cat = db["cards"].get(filename)
                
                # 1. 统一转成列表格式
                category_list = []
                if isinstance(raw_cat, list):
                    category_list = raw_cat
                elif isinstance(raw_cat, str) and raw_cat and raw_cat != "默认":
                    category_list = [raw_cat]
                
                # 2. 过滤掉已经删除的分类，只保留有效的
                valid_categories = [c for c in category_list if c in db["categories"]]
                # === 修复结束 ===

                # 获取备注
                remark = db["remarks"].get(filename, "")

                # 获取时间
                mtime = os.path.getmtime(filepath)
                date_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M')
                
                cards_list.append(meta | {
                    "filename": filename, 
                    "category": valid_categories, # 这里现在返回的是列表了
                    "date": date_str,
                    "remark": remark
                })
    
    return jsonify({
        "categories": db["categories"],
        "cards": cards_list
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    category = request.form.get('category')
    mode = request.form.get('mode', 'overwrite') # 获取模式：overwrite(覆盖) 或 new(新建)
    
    if category == '全部' or category == '默认': category = None
    
    if file and file.filename.endswith(('.png', '.json')):
        filename = file.filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # === 新增：如果是新建模式，且文件存在，则自动重命名 ===
        if mode == 'new' and os.path.exists(filepath):
            base, ext = os.path.splitext(filename)
            counter = 1
            # 循环查找可用的文件名，例如 file (1).png, file (2).png
            while os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], f"{base} ({counter}){ext}")):
                counter += 1
            filename = f"{base} ({counter}){ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # 保存文件
        file.save(filepath)
        
        db = load_db()
        if category:
            db["cards"][filename] = category
        else:
            # 如果是覆盖模式，且原来有分类，保留原分类；如果是新文件，没分类就是没分类
            # 这里简单处理：新上传的如果有重名但选了新建，它会被视为新文件，没有分类
            pass 
            
        save_db(db)
        return jsonify({'success': True})
    return jsonify({'error': 'Format error'}), 400

@app.route('/api/category/add', methods=['POST'])
def add_category():
    name = request.json.get('name')
    if not name: return jsonify({'error': '为空'}), 400
    db = load_db()
    if name not in db["categories"]:
        db["categories"].append(name)
        save_db(db)
    return jsonify({'success': True})

@app.route('/api/category/rename', methods=['POST'])
def rename_category():
    old_name = request.json.get('old_name')
    new_name = request.json.get('new_name')
    if not new_name or new_name == old_name: return jsonify({'success': True})
    
    db = load_db()
    if old_name in db["categories"]:
        idx = db["categories"].index(old_name)
        db["categories"][idx] = new_name
        # 遍历所有卡片，把列表里的旧名字换新名字
        for filename, cats in db["cards"].items():
            if isinstance(cats, list) and old_name in cats:
                cats[cats.index(old_name)] = new_name
        save_db(db)
    return jsonify({'success': True})

@app.route('/api/category/delete', methods=['POST'])
def delete_category():
    name = request.json.get('name')
    db = load_db()
    if name in db["categories"]:
        db["categories"].remove(name)
        # 遍历所有卡片，把删掉的分类从列表里移除
        for filename, cats in db["cards"].items():
            if isinstance(cats, list) and name in cats:
                cats.remove(name)
        save_db(db)
    return jsonify({'success': True})

@app.route('/api/card/move', methods=['POST'])
def move_card():
    filename = request.json.get('filename')
    category = request.json.get('category')
    db = load_db()
    
    # 确保当前文件有分类列表
    if filename not in db["cards"] or not isinstance(db["cards"][filename], list):
        db["cards"][filename] = []
        
    if category:
        # 如果已经在分类里，就删掉（反选）
        if category in db["cards"][filename]:
            db["cards"][filename].remove(category)
        # 如果不在，就加上（选中）
        else:
            db["cards"][filename].append(category)
            
    save_db(db)
    return jsonify({'success': True})

# 新增：备注更新接口
@app.route('/api/card/remark', methods=['POST'])
def update_remark():
    filename = request.json.get('filename')
    remark = request.json.get('remark')
    
    db = load_db()
    if remark:
        db["remarks"][filename] = remark
    else:
        # 如果备注为空，则删除记录
        if filename in db["remarks"]:
            del db["remarks"][filename]
            
    save_db(db)
    return jsonify({'success': True})

@app.route('/api/open_folder', methods=['POST'])
def open_folder():
    filename = request.json.get('filename')
    if not filename: return jsonify({'error': 'No filename'}), 400
    
    abs_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    folder_path = app.config['UPLOAD_FOLDER']

    try:
        system_name = platform.system()
        if system_name == "Windows":
            subprocess.run(['explorer', '/select,', abs_path])
        elif system_name == "Darwin": # Mac
            subprocess.run(['open', '-R', abs_path])
        else: # Linux
            subprocess.run(['xdg-open', folder_path])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/card/delete_file', methods=['POST'])
def delete_card_file():
    filename = request.json.get('filename')
    if not filename: return jsonify({'error': 'No filename'}), 400
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception as e:
            return jsonify({'error': f"删除失败: {str(e)}"}), 500
    
    db = load_db()
    # 删除卡片关联
    if filename in db["cards"]:
        del db["cards"][filename]
    # 删除备注关联
    if filename in db.get("remarks", {}):
        del db["remarks"][filename]
        
    save_db(db)
        
    return jsonify({'success': True})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/category/reorder', methods=['POST'])
def reorder_categories():
    new_order = request.json.get('categories')
    if not isinstance(new_order, list): return jsonify({'error': 'Invalid data'}), 400
    
    db = load_db()
    # 更新分类顺序
    db["categories"] = new_order
    save_db(db)
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)