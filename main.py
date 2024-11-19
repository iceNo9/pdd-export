import os
import sys
import time
import json
import asyncio
import csv
import threading
from datetime import datetime, timedelta
from pyppeteer import launch
from bs4 import BeautifulSoup


# 全局变量
stop_scrolling = True  #停止翻页
pause_scrolling = False #暂停翻页
exit_scrolling = False #退出翻页线程

enable_scraping = False #是能捕获
last_request_time = 0 #上次捕获时间
is_file_recorded = False  # 初始为 False，表示文件未记录

valid_orders_count = 0  # 记录有效订单的数量
down_scroll_count = 0 

start_time = None  # 起始时间
end_time = None  # 结束时间

# 存储所有符合要求的订单数据（避免重复保存）
stored_orders = {}

# 检测是否运行在打包环境中
if hasattr(sys, 'executable'):  # Nuitka 打包后会设置 sys.executable
    current_dir = os.path.dirname(sys.executable)
else:
    current_dir = os.path.dirname(os.path.abspath(__file__))

# 拼接 Chrome 浏览器路径
chrome_path = os.path.join(current_dir, 'chrome-win64', 'chrome.exe')

# print(f"当前目录: {current_dir}")
# print(f"Chrome路径: {chrome_path}")

# 添加反自动化检测处理
async def add_antidetect(page):
    """ 注入代码来绕过反自动化检测 """
    await page.evaluateOnNewDocument(''' 
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        })
    ''')
    await page.setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

# 模拟滚动翻页
async def simulate_scroll(page, wait_time=1, max_scroll_down=5):
    """ 一直滚动翻页，直到查询到的订单的 order_time 小于预设时间 """
    global stop_scrolling, pause_scrolling, down_scroll_count, exit_scrolling, is_file_recorded  # 引用全局变量
    # print("模拟滚动任务启动...")

    scroll_step = 200  # 每次向上滚动的像素距离，可以根据需要调整
    down_scroll_count = 0  # 初始化向下翻页计数器
    stop_keywords = ["没找到订单", "没有更多的订单"]  # 页面结束时的关键词列表
    while not exit_scrolling:
        while not stop_scrolling:
            # 暂停翻页：如果暂停标志为 True，暂停翻页直到处理完数据
            if pause_scrolling:
                # print("暂停翻页，等待数据处理完成...")
                await asyncio.sleep(wait_time)
                continue
                    
            # 等待页面加载稳定，避免上下文丢失
            await page.waitForSelector('body', {'timeout': 5000})  # 等待 body 元素加载完成
            
            # 检查页面是否包含停止滚动的关键词
            page_content = await page.evaluate("document.body.innerText")  # 获取页面的文本内容
            if any(keyword in page_content for keyword in stop_keywords):
                print("检测到页面底部提示内容，结束滚动...")
                stop_scrolling = True
                break

            # 每达到指定次数就执行向上翻页
            if down_scroll_count >= max_scroll_down:
                print(f"向下翻页 {max_scroll_down} 次后，准备向上翻页...")

                # 每次向上滚动一点点，而不是一次性滚动到顶部
                # 计算滚动的位置，这里使用 document.body.scrollHeight 来获取当前页面的总高度
                current_scroll_position = await page.evaluate("window.scrollY")  # 获取当前的滚动位置
                if current_scroll_position > scroll_step:
                    # 如果当前位置大于滚动步长，则逐步向上滚动
                    new_scroll_position = current_scroll_position - scroll_step
                    await page.evaluate(f"window.scrollTo(0, {new_scroll_position});")
                    print(f"向上滚动 {scroll_step} 像素...")
                else:
                    # 如果当前位置小于步长，直接滚动到顶部
                    await page.evaluate("window.scrollTo(0, 0);")
                    print("滚动到页面顶部...")
                down_scroll_count = 0  # 重置向下翻页计数器
            else:
                # 向下滚动页面
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                print("请保持窗口前台，滚动翻页中...")
                # 增加向下翻页次数计数
                down_scroll_count += 1

            # 等待一段时间加载更多数据
            await asyncio.sleep(wait_time)
        
        # 每次查找结束时检查是否记录文件
        if not is_file_recorded:
            save_to_csv()  # 保存文件
            is_file_recorded = True  # 设置标志为 True，表示文件已记录
        
# 时间戳转换为北京时间（UTC+8）
def convert_timestamp(timestamp):
    if timestamp:
        # 将 UTC 时间转为北京时间
        utc_time = datetime.utcfromtimestamp(timestamp)
        beijing_time = utc_time + timedelta(hours=8)
        return beijing_time.strftime('%Y-%m-%d %H:%M:%S')
    return ""

# 捕获网络请求的回调函数
async def intercept_request(response):
    global stop_scrolling, pause_scrolling, enable_scraping, stored_orders, last_request_time, start_time

    if 'order_list_v' not in response.url:
        return  # 跳过无关请求

    if not enable_scraping:
        return  # 非使能

    pause_scrolling = True  # 暂停翻页

    try:
        body = await response.text()
        orders = json.loads(body).get('orders', [])
    except json.JSONDecodeError:
        print(f"无法解析响应为 JSON，URL：{response.url}")
        return

    # 当前时间戳
    current_time = time.time()

    # 判断距离上次捕获的请求是否超过30秒，若超过，则停止翻页
    if last_request_time and current_time - last_request_time > 30:
        print("超过30秒未捕获到目标请求，停止翻页")
        stop_scrolling = True
        enable_scraping = False
        return

    # 更新上次捕获请求的时间
    last_request_time = current_time

    for order in orders:
        order_data = {
            'order_sn': order.get('order_sn'),
            'group_id': order.get('group_id'),
            'order_amount': order.get('order_amount'),
            'shipping_time': convert_timestamp(order.get('shipping_time')),
            'order_time': convert_timestamp(order.get('order_time')),
            'group_order_time': convert_timestamp(order.get('create_at')),
            'receive_time': convert_timestamp(order.get('receive_time')),
            'display_amount': order.get('display_amount') / 100,
            'mall_name': order.get('mall', {}).get('mall_name', ''),
            'order_status_prompt': order.get('order_status_prompt', '')
        }

        # 去重
        if order_data['order_sn'] in stored_orders:
            continue

        # 添加商品信息到 order_data
        for item in order.get('order_goods', []):
            goods_name = item.get('goods_name')
            spec = item.get('spec')
            order_data['goods_name'] = goods_name
            order_data['spec'] = spec

        # 存储订单数据
        stored_orders[order_data['order_sn']] = order_data

        # 处理符合时间条件的订单
        if order_data['order_time']:
            order_time = datetime.strptime(order_data['order_time'], '%Y-%m-%d %H:%M:%S')
            print(f"添加订单：{order_data['order_sn']}，order_time: {order_time}")

            # 判断是否小于起始时间减一年，若小于则停止抓取
            if not start_time == None:
                one_year_earlier = start_time - timedelta(days=365)
                if order_time < one_year_earlier:
                    print(f"订单 {order_data['order_sn']} 的 order_time: {order_time} 小于起始时间减一年，停止抓取")
                    stop_scrolling = True
                    enable_scraping = False  # 停止抓取
                    break  # 跳出循环，停止翻页

    # 恢复翻页：处理完数据后恢复翻页
    pause_scrolling = False
    
# 捕获网络请求的回调函数
async def intercept_request2(response):
    global stop_scrolling, pause_scrolling, enable_scraping, stored_orders

    if 'order_list_v' not in response.url:
        # print(f"其他请求{response.url}")
        return  # 跳过无关请求
    
    if not enable_scraping:
        return #非使能
    
    pause_scrolling = True #暂停翻页

    try:
        body = await response.text()
        orders = json.loads(body).get('orders', [])
    except json.JSONDecodeError:
        print(f"无法解析响应为 JSON，URL：{response.url}")
        return

    for order in orders:
        order_data = {
            'order_sn': order.get('order_sn'),
            'group_id': order.get('group_id'),
            'order_amount': order.get('order_amount'),
            'shipping_time': convert_timestamp(order.get('shipping_time')),
            'order_time': convert_timestamp(order.get('order_time')),
            'group_order_time': convert_timestamp(order.get('create_at')),
            'receive_time': convert_timestamp(order.get('receive_time')),
            'display_amount': order.get('display_amount') / 100,
            'mall_name': order.get('mall', {}).get('mall_name', ''),
            'order_status_prompt': order.get('order_status_prompt', '')
        }
        
        # 去重
        if order_data['order_sn'] in stored_orders:
            continue

        # 添加商品信息到 order_data
        for item in order.get('order_goods', []):
            goods_name = item.get('goods_name')
            spec = item.get('spec')
            order_data['goods_name'] = goods_name
            order_data['spec'] = spec
            
        # 存储订单数据
        stored_orders[order_data['order_sn']] = order_data        

        # 处理符合时间条件的订单
        if order_data['order_time']:
            order_time = datetime.strptime(order_data['order_time'], '%Y-%m-%d %H:%M:%S')
            print(f"添加订单：{order_data['order_sn']}，order_time: {order_time}")
            if 0:#order_time < start_time:
                print(f"订单 {order_data['order_sn']} 的 order_time: {order_time} 小于起始时间,goods_name: {order_data['goods_name']}，停止抓取")
                stop_scrolling = True
                enable_scraping = False  # 停止抓取
                break  # 跳出循环，停止翻页

            # if start_time <= order_time < end_time:
            #     print(f"有效订单：{order_data['order_sn']}，order_time: {order_time}")
            # valid_orders_count += 1
            # print(f"有效订单数：{valid_orders_count}，订单号：{order_data['order_sn']}，其 order_time: {order_time}")

    # 恢复翻页：处理完数据后恢复翻页
    pause_scrolling = False
  
# 对 stored_orders 根据 order_time 排序
def sort_stored_orders(by_order_time_desc=True):
    global stored_orders

    # 排序后的结果存储到新字典
    sorted_orders = {
        order_sn: data
        for order_sn, data in sorted(
            stored_orders.items(),
            key=lambda item: datetime.strptime(item[1]['order_time'], '%Y-%m-%d %H:%M:%S'),
            reverse=by_order_time_desc
        )
    }

    # 更新 stored_orders
    stored_orders = sorted_orders
    print(f"订单已按 {'降序' if by_order_time_desc else '升序'} 排序。")

# 存储数据到 CSV，按时间生成文件名
def save_to_csv():
    global stored_orders, valid_orders_count  # 使用全局存储的订单数据

    if not stored_orders:
        print("没有数据需要保存.")
        return

    # 获取字典中的最小和最大日期
    all_order_times = [datetime.strptime(order_data['order_time'], '%Y-%m-%d %H:%M:%S') for order_data in stored_orders.values()]
    min_date = min(all_order_times) if all_order_times else None
    max_date = max(all_order_times) if all_order_times else None

    # 根据条件设定 start_str 和 end_str
    if start_time:
        start_str = start_time.strftime('%Y%m%d')
    else:
        start_str = min_date.strftime('%Y%m%d') if min_date else 'unknown_start'

    if end_time:
        end_str = end_time.strftime('%Y%m%d')
    else:
        end_str = max_date.strftime('%Y%m%d') if max_date else 'unknown_end'

    filtered_csv_filename = f'{start_str}-{end_str}_filtered.csv'
    
    # 使用 min_date 和 max_date 来生成 full_csv_filename
    full_csv_filename = f'{min_date.strftime("%Y%m%d") if min_date else "unknown_start"}-{max_date.strftime("%Y%m%d") if max_date else "unknown_end"}_full.csv'

    # 对字典进行排序（默认降序）
    sort_stored_orders()

    # 公用字段名
    fieldnames = ['order_sn', 'group_id', 'order_amount', 'shipping_time', 'order_time', 'group_order_time', 
                  'receive_time', 'display_amount', 'mall_name', 'goods_name', 'spec', 'order_status_prompt']

    # 保存时间限定范围内的订单
    valid_orders_count = 0
    with open(filtered_csv_filename, 'w', encoding='utf-8', newline='') as filtered_csv:
        writer = csv.DictWriter(filtered_csv, fieldnames=fieldnames)
        writer.writeheader()  # 写入表头

        for order_sn, order_data in stored_orders.items():
            order_time = datetime.strptime(order_data['order_time'], '%Y-%m-%d %H:%M:%S')
            if start_time and not (start_time <= order_time < end_time):
                continue  # 跳过不符合时间范围的订单
            if not start_time and order_time < min_date:
                continue  # 跳过早于最小日期的订单
            if not end_time and order_time > max_date:
                continue  # 跳过晚于最大日期的订单

            valid_orders_count += 1
            writer.writerow(order_data)

    print(f"已保存 {valid_orders_count} 条有效订单到 {filtered_csv_filename}.")

    # 保存所有订单到另一份文件
    with open(full_csv_filename, 'w', encoding='utf-8', newline='') as full_csv:
        writer = csv.DictWriter(full_csv, fieldnames=fieldnames)
        writer.writeheader()  # 写入表头

        # 仅使用字典中的最小和最大日期来确定文件命名
        for order_data in stored_orders.values():
            writer.writerow(order_data)

    print(f"已保存 {len(stored_orders)} 条全部订单到 {full_csv_filename}.")

def save_to_csv2():
    global stored_orders, valid_orders_count  # 使用全局存储的订单数据

    # 只有在停止抓取时才保存数据
    if not stored_orders:
        print("没有数据需要保存.")
        return

    start_str = start_time.strftime('%Y%m%d')  # 格式化为 YYYYMMDD
    end_str = end_time.strftime('%Y%m%d')  # 格式化为 YYYYMMDD
    csv_filename = f'{start_str}-{end_str}.csv'

    # 对字典进行排序
    sort_stored_orders()
    
    
    file_exists = os.path.exists(csv_filename)

    # 打开 CSV 文件，追加模式
    with open(csv_filename, 'a', encoding='utf-8', newline='') as csvfile:
        fieldnames = ['order_sn', 'group_id', 'order_amount', 'shipping_time', 'order_time', 'group_order_time', 
                      'receive_time', 'display_amount', 'mall_name', 'goods_name', 'spec', 'order_status_prompt']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        # 如果文件不存在，写入表头
        if not file_exists:
            writer.writeheader()

        # 遍历存储的订单数据并写入 CSV
        for order_sn, order_data in stored_orders.items():
            # 订单时间检查：确保在起始时间和结束时间之间
            order_time = datetime.strptime(order_data['order_time'], '%Y-%m-%d %H:%M:%S')
            if not (start_time <= order_time < end_time):
                continue  # 跳过不符合时间范围的订单

            # 创建新的行字典，并添加商品信息
            row = order_data.copy()
            row['goods_name'] = order_data.get('goods_name')
            row['spec'] = order_data.get('spec')
            valid_orders_count += 1

            writer.writerow(row)

    print(f"已保存 {valid_orders_count} 条有效订单到 {csv_filename}")

def save_to_csv3():
    global stored_orders, valid_orders_count  # 使用全局存储的订单数据

    if not stored_orders:
        print("没有数据需要保存.")
        return

    start_str = start_time.strftime('%Y%m%d')  # 格式化为 YYYYMMDD
    end_str = end_time.strftime('%Y%m%d')  # 格式化为 YYYYMMDD
    filtered_csv_filename = f'{start_str}-{end_str}_filtered.csv'
    full_csv_filename = f'{start_str}-{end_str}_full.csv'

    # 对字典进行排序（默认降序）
    sort_stored_orders()

    # 公用字段名
    fieldnames = ['order_sn', 'group_id', 'order_amount', 'shipping_time', 'order_time', 'group_order_time', 
                  'receive_time', 'display_amount', 'mall_name', 'goods_name', 'spec', 'order_status_prompt']

    # 保存时间限定范围内的订单
    valid_orders_count = 0
    with open(filtered_csv_filename, 'w', encoding='utf-8', newline='') as filtered_csv:
        writer = csv.DictWriter(filtered_csv, fieldnames=fieldnames)
        writer.writeheader()  # 写入表头

        for order_sn, order_data in stored_orders.items():
            order_time = datetime.strptime(order_data['order_time'], '%Y-%m-%d %H:%M:%S')
            if not (start_time <= order_time < end_time):
                continue  # 跳过不符合时间范围的订单

            valid_orders_count += 1
            writer.writerow(order_data)

    print(f"已保存 {valid_orders_count} 条有效订单到 {filtered_csv_filename}.")

    # 保存所有订单到另一份文件
    with open(full_csv_filename, 'w', encoding='utf-8', newline='') as full_csv:
        writer = csv.DictWriter(full_csv, fieldnames=fieldnames)
        writer.writeheader()  # 写入表头

        for order_data in stored_orders.values():
            writer.writerow(order_data)

    print(f"已保存 {len(stored_orders)} 条全部订单到 {full_csv_filename}.")

# UI交互任务
def ui_interaction():
    global stop_scrolling, enable_scraping, start_time, end_time, exit_scrolling, is_file_recorded # 引用全局变量

    while True:
        print("\n请选择操作:")
        print("1. 设置起始时间")
        print("2. 设置结束时间")
        print("3. 启动抓取")
        print("4. 停止抓取")
        print("5. 退出浏览器")

        choice = input("请输入选项：")

        if choice == '1':
            set_time("设置起始时间:")
            # 添加设置起始时间的逻辑
        elif choice == '2':
            set_time("设置结束时间:")
            # 添加设置结束时间的逻辑
        elif choice == '3':
            if not enable_scraping:
                print(f"start_data: {start_time}, end_data: {end_time}")
                enable_scraping = True
                stop_scrolling = False
                pause_scrolling = False
                is_file_recorded = False
                valid_orders_count = 0
                last_request_time = 0
            else:
                print("抓取任务已经在运行中！")
        elif choice == '4':
            if enable_scraping:
                enable_scraping = False
                stop_scrolling = True
                pause_scrolling = True
                print("抓取暂停！")
            else:
                print("当前没有正在运行的抓取任务。")
        elif choice == '5':
            enable_scraping = False
            exit_scrolling = True
            stop_scrolling = True
            pause_scrolling = True
            break
            print("退出...")
        else:
            print("无效的选项，请重新输入。")

# 设置起始时间和结束时间
def set_time(prompt):
    while True:
        try:
            time_input = input(prompt).strip()
            time_parts = list(map(int, time_input.split()))
            if len(time_parts) < 3:
                raise ValueError("时间格式不正确，至少需要年月日")

            # 默认为 0 点 0 分 0 秒
            if len(time_parts) == 3:
                time_parts.extend([0, 0, 0])

            year, month, day, hour, minute, second = time_parts
            dt = datetime(year, month, day, hour, minute, second)

            if prompt == "设置起始时间:":
                global start_time
                start_time = dt
                print(f"起始时间已设置为: {start_time}")
            else:
                global end_time
                # 确保结束时间大于起始时间
                if start_time is not None and dt <= start_time:
                    print("结束时间必须大于起始时间，请重新输入。")
                    continue
                end_time = dt
                print(f"结束时间已设置为: {end_time}")

            break
        except ValueError as e:
            print(f"错误：{e}")

# 提取订单数据
async def extract_order_data_by_selector(page):
    global stored_orders
    try:
        # 等待 body 标签加载完成
        await page.waitForSelector('#orders > script:nth-child(3)', {'timeout': 10000})
        
        # 使用 CSS 选择器查找指定的 <script> 标签
        script_content = await page.evaluate(
            """
            () => {
                const scriptTag = document.querySelector('#orders > script:nth-child(3)');
                if (scriptTag) {
                    const scriptContent = scriptTag.innerHTML.trim();
                    if (scriptContent.includes('window.rawData')) {
                        const match = scriptContent.match(/window\\.rawData\\s*=\\s*({.*?});/s);
                        if (match && match[1]) {
                            return match[1];  // 返回 JSON 字符串部分
                        }
                    }
                }
                return null;
            }
            """
        )
        
        # with open('temp.txt', 'w', encoding='utf-8') as temp_file:
        #         temp_file.write(script_content)

        if script_content:
            # 尝试解析 JSON 数据
            try:
                # 解析 JSON 数据
                raw_data = json.loads(script_content)

                # # 保存 raw_data 到 temp1.txt
                # with open('temp1.txt', 'w', encoding='utf-8') as temp_file:
                #     temp_file.write(json.dumps(raw_data, indent=4, ensure_ascii=False))

                # 提取 ordersStore
                orders_store = raw_data.get('ordersStore', {})
                
                # # 保存 ordersStore 到 temp2.txt
                # with open('temp2.txt', 'w', encoding='utf-8') as temp_file:
                #     temp_file.write(json.dumps(orders_store, indent=4, ensure_ascii=False))

                # 提取 orders 数据
                orders = orders_store.get('orders', [])
                
                # # 保存 orders 到 temp3.txt
                # with open('temp3.txt', 'w', encoding='utf-8') as temp_file:
                #     temp_file.write(json.dumps(orders, indent=4, ensure_ascii=False))                    

                # 处理订单数据
                for order in orders:
    
                    order_data = {
                        'order_sn': order.get('orderSn'),
                        'group_id': order.get('groupId'),
                        'order_amount': order.get('orderAmount'),
                        'shipping_time': convert_timestamp(order.get('shippingTime')),
                        'order_time': convert_timestamp(order.get('orderTime')),
                        'group_order_time': convert_timestamp(order.get('create_at')),
                        'receive_time': convert_timestamp(order.get('receiveTime')),
                        'display_amount': order.get('displayAmount') / 100,
                        'mall_name': order.get('mall', {}).get('mallName', ''),
                        'order_status_prompt': order.get('orderStatusPrompt', '')
                    }

                    # 去重：如果订单已经存在，则跳过
                    if order_data['order_sn'] in stored_orders:
                        continue

                    # 添加商品信息到 order_data
                    for item in order.get('orderGoods', []):
                        goods_name = item.get('goodsName')
                        spec = item.get('spec')
                        order_data['goods_name'] = goods_name
                        order_data['spec'] = spec

                    # 存储订单数据
                    stored_orders[order_data['order_sn']] = order_data
                    print(f"添加订单：{order_data['order_sn']}, order_time: {order_data['order_time']}")
                    
            except json.JSONDecodeError as e:
                print(f"解析 JSON 数据时发生错误: {e}")
                print(f"raw_data_str 内容: {raw_data_str}")

    except Exception as e:
        print(f"提取初始订单数据时发生错误: {e}")

    
# 提取订单数据
async def extract_order_data_by_selector2(page):
    global stored_orders

    try:
        # 等待 body 标签加载完成
        await page.waitForSelector('body', {'timeout': 10000})

        # 使用 XPath 提取 /html/body/script[2]/text() 内容
        script_content = await page.evaluate(
            """
            () => {
                const script = document.evaluate(
                    '/html/body/script[2]',
                    document,
                    null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE,
                    null
                ).singleNodeValue;
                return script ? script.textContent : null;
            }
            """
        )

        # 如果 script 内容为空，打印错误信息并返回
        if not script_content:
            print("未找到 script 标签内容.")
            return

        # 打印提取到的 script 内容的前500个字符以便检查
        print(f"提取到的 script_content: {script_content[:500]}")

        # 从 script_content 中提取 window.rawData
        try:
            # 获取 window.rawData 的 JSON 部分
            raw_data_str = script_content.strip().lstrip('window.rawData = ').rstrip(';')
            if not raw_data_str:
                print("未能从 script_content 提取到有效的 rawData.")
                return

            # 打印提取到的 raw_data_str 以检查内容
            print(f"提取到的 raw_data_str: {raw_data_str[:500]}")  # 打印前 500 字符，检查内容

            # 尝试解析 JSON 数据
            raw_data = json.loads(raw_data_str)

            # 提取 orders 数据
            orders = raw_data.get('orders', [])
            if not orders:
                print("没有找到初始订单数据.")
                return

            # 处理订单数据
            for order in orders:
                order_data = {
                    'order_sn': order.get('order_sn'),
                    'group_id': order.get('group_id'),
                    'order_amount': order.get('order_amount'),
                    'shipping_time': convert_timestamp(order.get('shipping_time')),
                    'order_time': convert_timestamp(order.get('order_time')),
                    'group_order_time': convert_timestamp(order.get('create_at')),
                    'receive_time': convert_timestamp(order.get('receive_time')),
                    'display_amount': order.get('display_amount') / 100,
                    'mall_name': order.get('mall', {}).get('mall_name', ''),
                    'order_status_prompt': order.get('order_status_prompt', '')
                }

                # 去重：如果订单已经存在，则跳过
                if order_data['order_sn'] in stored_orders:
                    continue

                # 添加商品信息到 order_data
                for item in order.get('orderGoods', []):
                    goods_name = item.get('goodsName')
                    spec = item.get('spec')
                    order_data['goods_name'] = goods_name
                    order_data['spec'] = spec

                # 存储订单数据
                stored_orders[order_data['order_sn']] = order_data
                print(f"添加订单：{order_data['order_sn']}, order_time: {order_data['order_time']}")

        except json.JSONDecodeError as e:
            print(f"解析 JSON 数据时发生错误: {e}")
            print(f"raw_data_str 内容: {raw_data_str}")

    except Exception as e:
        print(f"提取初始订单数据时发生错误: {e}")



async def main():
    global stop_scrolling, enable_scraping, start_time, end_time  # 引用全局变量
    scraping_task = None  # 定义抓取任务变量

    # 启动浏览器
    browser = await launch(
        headless=False,
        executablePath=chrome_path,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
    )

    page = await browser.newPage()

    # 添加反自动化检测处理
    await add_antidetect(page)

    # 访问拼多多订单页面
    await page.goto("https://mobile.pinduoduo.com/orders.html")
    
    # 登录状态检查
    title = await page.title()
    if "登录" in title or "登录" in await page.content():
        print("未检测到登录状态，请手动登录。")
        input("完成登录按 Enter 键继续...")  # 登录后按 Enter 键继续
    else:
        print("已检测到登录状态，继续操作。")
            
    #导入初始数据
    await extract_order_data_by_selector(page)

    # 设置请求拦截器
    page.on('response', lambda response: asyncio.ensure_future(intercept_request(response)))

    # 启动UI交互线程
    ui_thread = threading.Thread(target=ui_interaction)
    ui_thread.daemon = True
    ui_thread.start()

    # 主任务循环
    try:
        while not exit_scrolling:  # 添加退出标志位的检查
            if enable_scraping:
                if scraping_task is None or scraping_task.done():
                    print(f"start_data: {start_time}, end_data: {end_time}")
                    scraping_task = asyncio.ensure_future(simulate_scroll(page))
                await scraping_task

            await asyncio.sleep(1)  # 等待下一次指令

    except Exception as e:
        print(f"主任务发生错误: {e}")

    finally:
        print("正在清理资源并退出...")
        await browser.close()  # 关闭浏览器
        print("已退出程序。")


# 主程序
async def main2():
    global stop_scrolling, enable_scraping, start_time, end_time # 引用全局变量

    # 启动浏览器
    browser = await launch(
        headless=False,  
        executablePath=chrome_path,  
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
    )

    page = await browser.newPage()

    # 添加反自动化检测处理
    await add_antidetect(page)

    # 访问拼多多订单页面
    await page.goto("https://mobile.pinduoduo.com/orders.html")
    
    # 登录状态检查
    title = await page.title()
    if "登录" in title or "登录" in await page.content():
        print("未检测到登录状态，请手动登录。")
        input("完成登录按 Enter 键继续...")  # 登录后按 Enter 键继续
    else:
        print("已检测到登录状态，继续操作。")

    # 设置请求拦截器
    page.on('response', lambda response: asyncio.ensure_future(intercept_request(response)))

    # 用户交互菜单
    while True:
        choice = display_menu()

        if choice == "1":
            set_time("设置起始时间")
        elif choice == "2":
            set_time("设置结束时间")
        elif choice == "3":
            # 启动抓取
            print(f"start_data: {start_time}, end_data: {end_time}")
            enable_scraping = True
            stop_scrolling = False
            pause_scrolling = False
            valid_orders_count = 0
            await simulate_scroll(page)
            enable_scraping = False
            stop_scrolling = True
            pause_scrolling = True
            save_to_csv()            
        elif choice == "4":
            # 停止抓取
            enable_scraping = False
            stop_scrolling = True
            pause_scrolling = True
            print("抓取已停止。")
        elif choice == "5":
            # 退出浏览器
            await browser.close()
            print("浏览器已关闭。")
            break
        else:
            print("无效的选项，请重新选择。")


# 主程序
async def main3():
    global stop_scrolling, enable_scraping, start_time, end_time  # 引用全局变量
    scraping_task = None  # 定义抓取任务变量

    # 启动浏览器
    browser = await launch(
        headless=False,
        executablePath=chrome_path,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
    )

    page = await browser.newPage()

    # 添加反自动化检测处理
    await add_antidetect(page)

    # 访问拼多多订单页面
    await page.goto("https://mobile.pinduoduo.com/orders.html")
    
    # 登录状态检查
    title = await page.title()
    if "登录" in title or "登录" in await page.content():
        print("未检测到登录状态，请手动登录。")
        input("完成登录按 Enter 键继续...")  # 登录后按 Enter 键继续
    else:
        print("已检测到登录状态，继续操作。")

    # 设置请求拦截器
    page.on('response', lambda response: asyncio.ensure_future(intercept_request(response)))
    
    # 启动翻页任务并传递 page 参数
    asyncio.run(run_scraping_task(page))  # 在 asyncio 事件循环中运行抓取任务

    # 启动UI交互线程
    ui_thread = threading.Thread(target=ui_interaction)
    ui_thread.daemon = True
    ui_thread.start()

    # 主线程等待退出
    while not exit_scrolling:
        time.sleep(1)
        

# 运行主程序
if __name__ == '__main__':
    asyncio.run(main())
