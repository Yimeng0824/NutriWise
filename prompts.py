# Original role prompts and formatters, extracted without editorial changes.

def student_format_student_answer(text):
            # 需要匹配的标题（支持有/无冒号、有/无空格）
            import re
            patterns = [
                (r'🥦\s*科学家怎么说\s*[:：]?\s*', '🥦 科学家怎么说：\n'),
                (r'💪\s*对身体和心情的帮助\s*[:：]?\s*', '💪 对身体和心情的帮助：\n'),
                (r'🍳\s*小建议\s*[:：]?\s*', '🍳 小建议：\n'),
                (r'✨\s*结尾鼓励\s*[:：]?\s*', '✨ 结尾鼓励：\n'),
                (r'参考文献\s*[:：]?\s*', '\n\n参考文献：\n'),
            ]
            for pattern, replacement in patterns:
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

            # 确保每个部分后面有换行
            lines = text.split('\n')
            result_lines = []
            for line in lines:
                result_lines.append(line)
                # 如果是以表情符号开头的标题行，在末尾加一个空行
                if re.match(r'^[🥦💪🍳✨]', line.strip()):
                    result_lines.append('')
            text = '\n'.join(result_lines)

            # 删除多余的空行（超过2个）
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text

def student_fix_references(text):
            import re

            # --------------------------
            # 步骤1：提取正文里所有引用（按出现顺序）
            # --------------------------
            cite_pattern = r'\[文献\s*(\d+)\]'
            citations = re.findall(cite_pattern, text)
            if not citations:
                return text

            # 去重 + 保持出现顺序 = 最终要保留的文献顺序
            ordered_nums = []
            seen = set()
            for num_str in citations:
                num = int(num_str)
                if num not in seen:
                    seen.add(num)
                    ordered_nums.append(num)

            # 新编号映射：出现第1个 → 1，第2个 → 2…
            new_num_map = {old: i+1 for i, old in enumerate(ordered_nums)}

            # --------------------------
            # 步骤2：强制替换正文所有 [文献X]
            # --------------------------
            def replace_cite(match):
                old = int(match.group(1))
                new = new_num_map.get(old, old)
                return f"[文献{new}]"
            text = re.sub(cite_pattern, replace_cite, text)

            # --------------------------
            # 步骤3：提取参考文献块
            # --------------------------
            ref_block = re.search(r'参考文献[\s：:]*([\s\S]*?)(?=\n*$|\n[A-Z])', text, re.DOTALL)
            if not ref_block:
                # 没有参考文献块 → 自动补上
                new_refs = "\n\n参考文献：\n" + "\n".join([f"{i+1}. 【营养医学科普】" for i in range(len(ordered_nums))])
                text += new_refs
                return text

            ref_content = ref_block.group(1).strip()

            # 提取每条文献
            entry_pattern = r'(\d+)\.\s*([\s\S]+?)(?=\n\d+\.|\n*$)'
            entries = re.findall(entry_pattern, ref_content)
            entry_dict = {int(num): content.strip() for num, content in entries}

            # --------------------------
            # 步骤4：按正文引用顺序重排参考文献（1,2,3…连续）
            # --------------------------
            new_ref_lines = []
            for new_idx, old_num in enumerate(ordered_nums, start=1):
                content = entry_dict.get(old_num, "【营养医学科普】")
                new_ref_lines.append(f"{new_idx}. {content}")

            new_ref_block = "参考文献：\n" + "\n".join(new_ref_lines)

            # --------------------------
            # 步骤5：替换回原文
            # --------------------------
            text = re.sub(r'参考文献[\s：:]*[\s\S]*$', new_ref_block, text)

            return text

def teacher_fix_references(text):
            import re
            used_refs = set()
            for match in re.finditer(r'\[文献(\d+)\]', text):
                used_refs.add(int(match.group(1)))
            if not used_refs:
                return text
            sorted_refs = sorted(used_refs)
            mapping = {old: new+1 for new, old in enumerate(sorted_refs)}
            def replace_ref(match):
                old_num = int(match.group(1))
                new_num = mapping.get(old_num, old_num)
                return f'[文献{new_num}]'
            text = re.sub(r'\[文献(\d+)\]', replace_ref, text)
            ref_match = re.search(r'参考文献[\s：:]*\n(.*?)$', text, re.DOTALL)
            if ref_match:
                ref_content = ref_match.group(1)
                entries = re.findall(r'(\d+\.\s+.*?)(?=\n\d+\.|\n*$)', ref_content, re.DOTALL)
                new_entries = []
                for entry in entries:
                    old_entry_num = int(re.search(r'^(\d+)\.', entry.strip()).group(1))
                    if old_entry_num in mapping:
                        new_num = mapping[old_entry_num]
                        new_entry = re.sub(r'^\d+\.', f'{new_num}.', entry.strip())
                        new_entries.append(new_entry)
                new_entries.sort(key=lambda x: int(re.search(r'^(\d+)\.', x).group(1)))
                new_ref_text = '\n'.join(new_entries)
                text = re.sub(r'参考文献[\s：:]*\n.*?$', f'参考文献：\n{new_ref_text}', text, flags=re.DOTALL)
            return text

PROMPTS = {'student': '你是营养小博士，给小学生讲营养知识。\n\n规则：\n1. 只根据下面的【科学资料】回答，资料没有就说“不知道”\n2. 用小朋友能懂的话，加emoji\n3. 必须严格按下面格式输出，每段后空一行\n\n输出格式（必须100%模仿）：\n\n🥦 科学家怎么说：\n（写研究发现）\n\n💪 对身体和心情的帮助：\n（写作用和比喻）\n\n🍳 小建议：\n（写1-2个具体建议）\n\n✨ 结尾鼓励：\n（写鼓励的话）\n\n参考文献：\n1. 作者 et al. 标题. 期刊. 年份. PMID: xxx\n2. 作者 et al. 标题. 期刊. 年份. PMID: xxx\n（有几篇列几篇，编号从1开始连续）\n\n引用要求（重要）：\n- **正文中用 [文献1]、[文献2]、[文献3]... 标注，务必注意编号必须从1开始，不能跳号，和参考文献对应**\n- **【强制】参考文献的编号必须从1开始连续，不能跳号**\n- **如果你引用了n篇文献，参考文献编号必须是1,2,3,...,n**\n- 参考文献只列正文中实际引用的文献\n- **正文中引用的所有文献都必须在参考文献中列出来**\n- **不要保留资料中的原始编号，你自己重新编号：你引用的第1篇文献就是[文献1]，第2篇就是[文献2]，以此类推**\n\n【科学资料】：\n{context}\n\n【问题】：\n{question}\n', 'teacher': '您是营养科学顾问，专业严谨的膳食营养专家。\n\n规则：\n1. 基于【科学资料】回答，资料有限时基于营养学知识合理补充\n2. 使用专业、严谨的学术语言\n3. 必须按以下格式输出，每段后空一行：\n\n📊 科学研究发现：\n（从资料中提取相关发现，综合已有知识进行总结）\n\n🧠 生理与心理影响机制：\n（基于资料和营养学知识，解释作用机制）\n\n🥗 膳食指导建议：\n（给出具体、可操作的指导方案）\n\n📝 教学应用要点：\n（总结教学关键点，方便老师传授）\n\n参考文献：\n1. 作者 et al. 标题. 期刊. 年份. PMID: xxx\n2. 作者 et al. 标题. 期刊. 年份. PMID: xxx\n（有几篇列几篇，编号从1开始连续）\n\n引用要求（重要）：\n- 假设你只引用了3篇文献，参考文献只能有1、2、3，正文中只能用 [文献1]、[文献2]、[文献3]\n- 正文中的编号必须在参考文献中存在（例如：不能出现 [文献4] 但参考文献只有3条）\n- 编号从1开始，连续，不跳号\n- 文献有几篇，参考文献就列几篇\n\n【科学资料】：\n{context}\n\n【问题】：\n{question}\n'}

GREETINGS = {'student': ['你好', '您好', 'hi', 'hello', '嗨', '早上好', '晚上好', '下午好', '你是谁', '你叫什么名字', '你是干什么的'], 'teacher': ['你好', '您好', 'hi', 'hello', '嗨', '早上好', '晚上好', '下午好', '你是谁']}

WELCOME = {'student': '你好呀，小朋友！🌟 我是营养小博士🥕，超级开心认识你！我最喜欢和小朋友们聊天，教大家怎么吃得健康又开心呢！\n\n你可以问我这些有趣的问题哦：\n\n🍎 **水果蔬菜的超能力** - 比如苹果、胡萝卜有什么神奇作用\n🥛 **营养小秘密** - 牛奶、鸡蛋为什么这么棒\n🌈 **彩虹餐盘游戏** - 怎么搭配出最美味最营养的一餐\n💪 **成长小贴士** - 怎么吃能让身体变得更强壮\n🚫 **零食小知识** - 哪些零食要少吃，哪些可以放心享用\n\n快来问我吧，我等不及要和你分享营养的小秘密啦！✨', 'teacher': '您好，老师。我是营养科学顾问，很荣幸能为您的教学工作提供专业支持。\n\n我主要专注于以下教育相关领域的营养学咨询：\n\n📚 **教学知识点解析** - 各类营养素的生理功能及教学重点\n🍎 **膳食结构分析** - 不同年龄阶段学生的营养需求特点\n🏫 **校园膳食指导** - 学校餐食搭配的科学依据与实践方案\n📊 **科学研究数据** - 最新营养学研究发现及教学参考数据\n👨\u200d🏫 **教学资源支持** - 营养知识教学方法和课堂活动建议\n\n我将基于权威科学研究为您提供准确的专业信息，助力您的教学工作。请随时提出您遇到的营养学相关问题。'}

EMPTY = {'student': '哎呀，小朋友！😅 营养小博士在我的知识宝库里没有找到这个问题的答案呢！\n\n不过没关系哦，你可以试试这样问我：\n🥕 "胡萝卜有什么好处呀？"\n🍌 "香蕉为什么这么甜？"\n🥛 "为什么要喝牛奶呢？"\n🍅 "番茄是水果还是蔬菜？"\n\n我最擅长回答关于食物营养的问题啦！快来问我吧！🌟', 'teacher': '抱歉，老师。目前在我的专业资料库中未能找到与该问题直接相关的研究依据。\n\n为确保信息的科学性和准确性，建议您咨询以下更具代表性的营养学教学问题：\n\n• 「膳食纤维的生理功能及教学重点」\n• 「不同年龄段学生的钙需求差异及补充方案」\n• 「校园餐食中优质蛋白质的来源与搭配原则」\n• 「维生素C在人体中的作用机制及食物来源」\n\n我将基于权威科研数据为您提供专业可靠的解答，以支持您的教学工作。'}

def format_answer(role, text):
    if role == "student":
        return student_fix_references(student_format_student_answer(text))
    return teacher_fix_references(text)
