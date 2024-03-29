import random
import signal
from pathlib import Path

import psutil
from selenium_scripts import *
from scraper_scripts import *

import moviepy.editor as mp
from moviepy.editor import AudioFileClip, ImageClip
from mutagen.mp3 import MP3

from pprint import pprint

from gtts import gTTS

from multiprocessing import Pool

import praw

import urllib3

from telegram import Update
from telegram.ext import CallbackContext
from telegram.ext import CommandHandler
from telegram.ext import Updater

import asyncio

# region Constants and Config

urllib3.disable_warnings()

logger = Logger()

run = True
hold = False

config = {
    'pool_size': 5,
    'width': 600,
    'max_video_length': 60,
    'short_timeout': 0.3,
    'long_timeout': 5,
    'page_load_timeout': 15,
    'sort_limit_default': 50,
    'reddit_client_id': "",
    'reddit_client_secret': "",
    'reddit_user_agent': "",
    'credentials_path': "credentials.json",
    'input_path': "farmer_input.csv"
}

credentials = {
    'reddit_client_id': "",
    'client_secret': "",
    'user_agent': "",
    'telegram_bot_token': "",
    'telegram_primary_chat_id': ""
}

time_filter_map = {
    'h': "hour",
    'd': "day",
    'w': "week",
    'm': "month",
    'y': "year",
    'a': "all"
}

config.update(get_configurations('config.txt'))

with open(config['credentials_path'], 'r', encoding='utf-8') as json_file:
    credentials.update(json.load(json_file))

config.update(credentials)

print("Credentials: ", credentials)


# endregion


# region Content Creation

def parse_farmer_input_file() -> list[dict]:
    data = []
    with open(config['input_path'], 'r', encoding='utf-8') as input_file:
        reader = csv.reader(input_file)
        raw_data = list(reader)

        for row in raw_data:
            # Parse Comment or Malformed Row
            if row[1][0] == '!' or len(row) < 4:
                continue

            batch_input = {
                'fetch_mode': row[0],
                'subreddit_array': row[1],
                'fetch_settings': row[2],
                'submission_limit': int(row[3]),
                'comment_limit': int(row[4]) if len(row) >= 5 else 5,
            }

            data.append(batch_input)

    return data


def parse_farmer_input(batch_order: str) -> dict:
    # Parse Comment or Malformed Row
    batch_order = batch_order.split(',')

    batch_input = {
        'fetch_mode': batch_order[0],
        'subreddit_array': batch_order[1],
        'fetch_settings': batch_order[2],
        'submission_limit': int(batch_order[3]),
        'comment_limit': int(batch_order[4]) if len(batch_order) >= 5 else 5,
    }

    return batch_input


def merge_audio_png(image_path: str, audio_path: str, out_path: str) -> bool:
    audio_clip = AudioFileClip(audio_path)
    image_clip = ImageClip(image_path)

    video_clip = image_clip.set_audio(audio_clip)
    video_clip.duration = audio_clip.duration
    video_clip.fps = 24

    video_clip.write_videofile(out_path, verbose=False, temp_audiofile=out_path.replace('.mp4', '-temp.mp4'))

    return True


def resize_by_width(target_width: int, video_path: str) -> mp.VideoFileClip:
    clip = mp.VideoFileClip(video_path)
    clip_resized = clip.resize(
        width=target_width)
    clip_resized.write_videofile(video_path, verbose=False, temp_audiofile=video_path.replace('.mp4', '-temp.mp4'))

    return clip


def fetch_post_content(driver, post_raw, output_path, inp):
    post = {
        'id': None,
        'name': None,
        'title': None,
        'post_hint': None,
        'created_utc': None,
        'over_18': None,
        'url': None,
        'selftext': ""
    }

    post_merge_info = {
        'path': "",
        'post': {
            'audio_path': "",
            'image_path': "",
        },
        'comments': [
        ]
    }

    current_length = 0

    post_raw = post_raw.__dict__

    for key in post.keys():
        post[key] = post_raw.get(key)

    pprint(post)

    post_path = output_path + post['id'] + '/'
    os.makedirs(post_path, exist_ok=True)

    post_merge_info['path'] = post_path

    post_text = post['title'] + "\n" * 2 + post['selftext']
    post_txt_path = post_path + "post.txt"
    f = open(post_txt_path, 'w', encoding='utf-8')
    f.write(post_text)
    f.close()

    post_audio = gTTS(text=post_text, lang='en', slow=False)
    post_audio_path = post_path + "post.mp3"
    post_audio.save(post_audio_path)

    current_length += MP3(post_audio_path).info.length

    driver.get(post['url'])

    post_image_path = post_path + 'post.png'
    driver.find_element(By.XPATH, '//div[contains(@data-test-id,"post-content")]').screenshot(post_image_path)

    post_merge_info['post'] = {'audio_path': post_audio_path, 'image_path': post_image_path}

    # post_video_path = post_path + "post.mp4"
    # merge_audio_png(post_image_path, post_audio_path, post_video_path)
    #
    # post_final_clip = resize_by_width(int(config['width']), post_video_path)

    comments = [span.find_element(By.XPATH, './parent::div/parent::div') for span in
                driver.find_elements(By.XPATH, '//span[contains(text(),"level 1")]')]

    # region Scroll Effectively

    scroll_element_selector = (By.XPATH, '//body')
    scroll_element = find(driver, *scroll_element_selector)
    last_height = scroll_element.size['height']

    for n in range(30):

        if len(comments) >= inp['comment_limit']:
            break
        else:
            # pyautogui.scroll(-5000)
            driver.find_element(By.TAG_NAME, 'html').send_keys(Keys.END)
            time.sleep(config['short_timeout'])
            scroll_element = find(driver, *scroll_element_selector)
            new_height = scroll_element.size['height']
            if new_height == last_height:
                break
            last_height = new_height
            time.sleep(config['short_timeout'])
            comments = driver.find_elements(By.XPATH,
                                            '//span[contains(text(),"level 1")]/parent::div/parent::div')

    # endregion

    # scroll_down_until_stop(driver, (By.XPATH, '//body'))

    time.sleep(config['long_timeout'])

    for n, comment_div in enumerate(comments[:inp['comment_limit']]):
        # Scroll to center

        desired_y = (comment_div.size['height'] / 2) + comment_div.location['y']
        window_h = driver.execute_script('return window.innerHeight')
        window_y = driver.execute_script('return window.pageYOffset')
        current_y = (window_h / 2) + window_y
        scroll_y_by = desired_y - current_y
        driver.execute_script("window.scrollBy(0, arguments[0]);", scroll_y_by)
        time.sleep(config['short_timeout'])

        comment_image_path = post_path + str(n) + '.png'
        comment_div.screenshot(comment_image_path)

        comment_text = regulate_string(
            comment_div.find_element(By.XPATH, './/div[@data-testid="comment"]').text)

        comment_txt_path = post_path + str(n) + '.txt'

        f = open(comment_txt_path, 'w', encoding='utf-8')
        f.write(comment_text)
        f.close()

        comment_audio_path = post_path + str(n) + '.mp3'

        comment_audio = gTTS(text=comment_text, lang='en', slow=False)
        comment_audio.save(comment_audio_path)

        if current_length + MP3(comment_audio_path).info.length > 60:
            break

        current_length += MP3(comment_audio_path).info.length
        print(current_length)

        post_merge_info['comments'].append({
            'audio_path': comment_audio_path,
            'image_path': comment_image_path
        })

        # comment_video_path = post_path + str(n) + '.mp4'
        # merge_audio_png(comment_image_path, comment_audio_path, comment_video_path)
        # comment_clip = resize_by_width(int(config['width']), comment_video_path)

        # clips = [post_final_clip, comment_clip]
        # post_final_clip = mp.concatenate_videoclips(clips, method="compose")

    # post_final_clip.write_videofile(post_path + "final.mp4")

    with open(post_path + "merge.json", "w", encoding='utf-8') as write_file:
        json.dump(post_merge_info, write_file, indent=4)

    print('\n' * 10)


def merge_post(merge_info: dict):
    try:
        post = merge_info['post']

        merge_audio_png(post['image_path'], post['audio_path'], merge_info['path'] + "final.mp4")
        post_final_clip = resize_by_width(int(config['width']), merge_info['path'] + "final.mp4")

        for n, comment in enumerate(merge_info['comments']):
            try:
                comment_video_path = merge_info['path'] + str(n) + '.mp4'
                merge_audio_png(comment['image_path'], comment['audio_path'], comment_video_path)
                comment_clip = resize_by_width(int(config['width']), comment_video_path)

                clips = [post_final_clip, comment_clip]
                post_final_clip = mp.concatenate_videoclips(clips, method="compose")
            except:
                logger.log_error()

        post_final_clip.write_videofile(merge_info['path'] + "final.mp4", verbose=False,
                                        temp_audiofile=merge_info['path'] + "final-temp.mp4")
    except:
        logger.log_error(f"Error at post merge {merge_info}")


async def multiprocess_merge_all_posts():
    merge_infos = []
    for path in Path('./archive/').rglob('merge.json'):
        with open(path, 'r', encoding='utf-8') as merge_file:
            merge_info = json.load(merge_file)
            merge_infos.append(merge_info)

    print(merge_infos)
    pool = Pool(5)
    pool.map(merge_post, merge_infos)
    pool.join()

    priv_bot.send_message(chat_id=credentials['telegram_primary_chat_id'],
                          text=f"Queued order of merging is done successfully.")


async def merge_all_posts():
    for path in Path('./archive/').rglob('merge.json'):
        with open(path, 'r', encoding='utf-8') as merge_file:
            merge_info = json.load(merge_file)
            merge_post(merge_info)

    priv_bot.send_message(chat_id=credentials['telegram_primary_chat_id'],
                          text=f"Queued order of merging is done successfully.")


async def fetch_qa_content_from_batch(driver: selenium.webdriver.Chrome, inp: dict):
    os.makedirs('./archive/' + inp['subreddit_array'], exist_ok=True)

    output_path = './archive/' + inp['subreddit_array'] + '/'

    subreddit_key = inp['subreddit_array']
    submission_count = inp['submission_limit']

    time_filter = 'week'
    if inp['fetch_settings'][0] == 't':
        time_filter = time_filter_map[inp['fetch_settings'][1]]

    fetch_subreddit = {
        # Hot
        'h': reddit.subreddit(subreddit_key).hot(limit=submission_count),
        # Top
        't': reddit.subreddit(subreddit_key).top(time_filter=time_filter, limit=submission_count),
        # New
        'n': reddit.subreddit(subreddit_key).new(limit=submission_count),
        # Rising
        'r': reddit.subreddit(subreddit_key).rising(limit=submission_count),
        # Gilded
        'g': reddit.subreddit(subreddit_key).gilded(limit=submission_count),
        # Controversial
        'c': reddit.subreddit(subreddit_key).controversial(limit=submission_count)
    }

    try:
        posts = fetch_subreddit[inp['fetch_settings'][0]]

        for post_raw in posts:
            try:
                fetch_post_content(driver, post_raw, output_path, inp)
            except Exception:
                logger.log_error()
    except Exception as e:
        logger.log_error(f"Error at fetching post content")
        priv_bot.send_message(chat_id=credentials['telegram_primary_chat_id'],
                              text=f"Queued order {inp} is done with error {e}.")
    else:
        priv_bot.send_message(chat_id=credentials['telegram_primary_chat_id'],
                              text=f"Queued order {inp} is done successfully.")


# endregion


# region Telegram

def kill_child_processes(parent_pid, sig=signal.SIGTERM):
    try:
        parent = psutil.Process(parent_pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    print(children)
    for process in children:
        process.send_signal(sig)
        process.kill()

    try:
        os.system('taskkill /F /IM "chrome.exe" /T')
    except:
        logger.log_error(f"Error at taskkil")


def telegram_start(update: Update, context: CallbackContext):
    context.bot.send_message(chat_id=update.effective_chat.id, text=update.effective_chat.id)


def telegram_fetch(update: Update, context: CallbackContext):
    global loop

    try:
        inp = parse_farmer_input(context.args[0])
    except:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Batch order could not be parsed")
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Opening browser")
        driver = get_driver(minimized=False,
                            options=[r"--user-data-dir=C:\Users\ofaru\AppData\Local\Google\Chrome\User Data",
                                     r'--profile-directory=Profile 8'])
        driver.set_window_size(600, 800)

        if inp['fetch_mode'] == 'qa':
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=f"Queueing q&a content farm using order {inp}")
            add_coroutine_to_main(fetch_qa_content_from_batch(driver, inp))


def telegram_merge(update: Update, context: CallbackContext):
    global loop

    if context.args and context.args[0] == 'singular':
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=f"Queueing merging of content components")
        add_coroutine_to_main(merge_all_posts())

    else:
        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=f"Queueing multiprocessor merging of content components")

        add_coroutine_to_main(multiprocess_merge_all_posts())


updater = Updater(token=credentials['telegram_bot_token'], use_context=True)
dispatcher = updater.dispatcher

priv_bot = updater.bot
priv_bot.send_message(chat_id=credentials['telegram_primary_chat_id'], text="Start up")


async def telegram_loop():
    start_handler = CommandHandler('start', telegram_start, run_async=True)
    dispatcher.add_handler(start_handler)

    fetch_handler = CommandHandler('fetch', telegram_fetch, run_async=True)
    dispatcher.add_handler(fetch_handler)

    merge_handler = CommandHandler('merge', telegram_merge, run_async=True)
    dispatcher.add_handler(merge_handler)

    updater.start_polling()


# endregion

tasks = []


def add_coroutine_to_main(coroutine: asyncio.futures):
    t = loop.create_task(coroutine)
    tasks.append(t)


async def main():
    await asyncio.sleep(5)

    if tasks:
        await asyncio.gather(*tasks)

    tasks.clear()


if __name__ == '__main__':
    reddit = praw.Reddit(
        # client_id=config['reddit_client_id'],
        client_id="-JMhRhnfIQrN6W8q3jSgAg",
        # client_secret=config['reddit_client_secret'],
        client_secret="HgOqMKOCcUfe7TvbVcuN91dXdJhadg",
        # user_agent=str(config['reddit_user_agent']).strip(),
        user_agent="ContentCreator Fetch content at a reasonable rate"
    )

    loop = asyncio.get_event_loop()
    try:
        loop.create_task(main())
        loop.create_task(telegram_loop())
        loop.run_forever()
    finally:
        updater.stop()

        pending = asyncio.all_tasks(loop=loop)
        for task in pending:
            task.cancel()

        loop.stop()
        loop.close()
