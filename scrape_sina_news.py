import asyncio
import argparse
import json
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# 设置全局超时（秒）
GLOBAL_TIMEOUT = 30000  # 30秒

class SinaNewsCrawler:
    def __init__(self, keywords, max_pages=5, output_dir='output'):
        self.keywords = keywords
        self.max_pages = max_pages
        self.output_dir = output_dir
        self.results = []
        os.makedirs(output_dir, exist_ok=True)
    
    async def process_news_item(self, item, page_num):
        """并发处理单个新闻条目"""
        try:
            # 提取标题 - 更新选择器
            title_elem = await item.query_selector('a')
            if not title_elem:
                return
            title = await title_elem.text_content()
            title = title.strip() if title else ""
            
            # 提取摘要 - 更新选择器
            summary_elem = await item.query_selector('p')
            summary = await summary_elem.text_content() if summary_elem else ""
            summary = summary.strip() if summary else ""
            
            # 提取链接
            link = await title_elem.get_attribute('href')
            if not link:
                return
            
            # 关键词过滤（匹配标题或摘要）
            if self.keywords and not any(kw in title or kw in summary for kw in self.keywords):
                return
            
            # 存储结果
            self.results.append({
                'title': title,
                'summary': summary,
                'url': link,
                'page': page_num
            })
            print(f"✅ 匹配新闻: {title}")
            
        except Exception as e:
            print(f"处理新闻条目出错: {e}")
    
    async def scrape_page(self, page, page_num):
        """爬取单个列表页"""
        try:
            # 等待新闻列表加载 - 使用更通用的选择器
            await page.wait_for_selector('.news-list', timeout=GLOBAL_TIMEOUT)
            
            # 获取所有新闻条目 - 更新选择器
            news_items = await page.query_selector_all('.news-list li')
            print(f"第{page_num}页找到{len(news_items)}条新闻")
            
            # 创建任务列表并发处理新闻条目
            tasks = [self.process_news_item(item, page_num) for item in news_items]
            await asyncio.gather(*tasks)
            
            return True
        except PlaywrightTimeoutError:
            print(f"第{page_num}页加载超时")
            return False
        except Exception as e:
            print(f"爬取第{page_num}页时发生错误: {e}")
            return False
    
    async def run(self):
        """运行爬虫"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            
            # 拦截不必要的资源（如图片）以加快加载速度
            await context.route('**/*.{png,jpg,jpeg,gif,svg}', lambda route: route.abort())
            
            page = await context.new_page()
            
            # 起始页（注意：新浪新闻分页URL特殊，直接通过点击翻页）
            # 使用更可靠的URL格式并添加加载状态等待
            start_url = "https://news.sina.com.cn/roll"
            await page.goto(start_url, timeout=GLOBAL_TIMEOUT)
            await page.wait_for_load_state('networkidle', timeout=GLOBAL_TIMEOUT)
            
            # 确保页面正确加载
            await page.wait_for_selector('.news-item', timeout=GLOBAL_TIMEOUT)
            
            current_page = 1
            while current_page <= self.max_pages:
                print(f"开始爬取第{current_page}页...")
                success = await self.scrape_page(page, current_page)
                if not success:
                    break
                
                # 每页爬取完成后进行增量保存
                if self.results:
                    print(f"准备保存{len(self.results)}条结果...")
                    self.save_results(incremental=True)
                else:
                    print(f"第{current_page}页未找到匹配新闻")
                
                # 翻页
                if current_page < self.max_pages:
                    try:
                        next_btn = await page.query_selector('a.next')
                        if next_btn:
                            await next_btn.click()
                            await page.wait_for_load_state('networkidle', timeout=GLOBAL_TIMEOUT)
                            current_page += 1
                        else:
                            print("未找到下一页按钮，爬取结束")
                            break
                    except PlaywrightTimeoutError:
                        print("翻页超时，爬取结束")
                        break
                    except Exception as e:
                        print(f"翻页失败: {e}")
                        break
                else:
                    break
            
            await browser.close()
    
    def save_results(self, incremental=False):
        """保存结果到JSON文件"""
        if not self.results:
            print("未获取到匹配的新闻")
            return
        
        if not hasattr(self, 'filename'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.filename = os.path.join(self.output_dir, f"sina_news_{timestamp}.json")
        
        mode = 'a' if incremental and os.path.exists(self.filename) else 'w'
        
        with open(self.filename, mode, encoding='utf-8') as f:
            if mode == 'w' or not os.path.exists(self.filename) or os.path.getsize(self.filename) == 0:
                # 新文件：写入完整的JSON数组
                f.write('[\n')
                json.dump(self.results, f, ensure_ascii=False, indent=2)
                f.write('\n]')
            else:
                # 追加数据到现有文件
                # 移除文件末尾的']'
                f.seek(0, os.SEEK_END)
                f.seek(f.tell() - 2, os.SEEK_SET)
                f.truncate()
                
                # 添加逗号和新数据
                f.write(',\n')
                json.dump(self.results, f, ensure_ascii=False, indent=2)
                f.write('\n]')
        
        print(f"已{'增量' if incremental else ''}保存结果到: {self.filename}")
        
        # 清空结果以释放内存
        self.results = []

def main():
    # 命令行参数解析
    parser = argparse.ArgumentParser(description='新浪新闻爬取工具')
    parser.add_argument('--keywords', nargs='+', required=True, help='关键词列表')
    parser.add_argument('--max_pages', type=int, default=5, help='最大爬取页数')
    args = parser.parse_args()
    
    # 运行爬虫
    crawler = SinaNewsCrawler(args.keywords, args.max_pages)
    asyncio.run(crawler.run())
    
    # 保存最终结果（确保文件正确关闭）
    if hasattr(crawler, 'filename'):
        with open(crawler.filename, 'r+', encoding='utf-8') as f:
            content = f.read()
            f.seek(0)
            f.write(content.replace(',\n]', '\n]'))
            f.truncate()

if __name__ == "__main__":
    main()