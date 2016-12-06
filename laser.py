#!/usr/bin/python

import os, sys, json
from random import choice, randint, sample
from collections import Counter, defaultdict
from subprocess import call
import shutil # for downloading images

import requests
from twitter import *
import sqlite3

#### command modes
doinitdb = (len(sys.argv) > 1 and sys.argv[1] == 'initdb')
justranking = (len(sys.argv) > 1 and sys.argv[1] == 'justranking')
nopost = (len(sys.argv) > 1 and sys.argv[1] == 'nopost')

#### parameters

seed_val  = 10000
rt_val    =  1500
fav_val   =   500
threshold =  200

# API keys
KEYS = {}

def bloop(ss):
    # print debugging info
    print('-----| ' + ss + ' |-----')

def uniq(ll):
    return list(set(ll))

# This is where this script is
path = os.path.dirname(os.path.realpath(sys.argv[0]))
bot_name = open('name').read().strip()
# put your app key and secret in this file
creds = json.loads(open(path + "/twitter-creds.json").read())
CONSUMER_KEY = creds['key']
CONSUMER_SECRET = creds['secret']
MY_TWITTER_CREDS = path + '/' + bot_name + '.auth'
if not os.path.exists(MY_TWITTER_CREDS):
    oauth_dance(bot_name, CONSUMER_KEY, CONSUMER_SECRET, MY_TWITTER_CREDS)

oauth_token, oauth_secret = read_token_file(MY_TWITTER_CREDS)

twitter = Twitter(auth=OAuth(oauth_token, oauth_secret, CONSUMER_KEY, CONSUMER_SECRET))

def init_db():
    conn = sqlite3.connect('showme.db')
    conn.execute("""create table source (
      source text primary key not null,
      imgurl text)""")
    
    conn.execute("""create table tweet (
      tweetid text primary key not null,
      source text, 
      faves int,
      rts int)""")

    conn.execute("""create table source_aspect (
      source text not null,
      aspect text not null,
      primary key (source, aspect))""")

    conn.execute("""create table key (
      service text primary key not null,
      key text not null)""")

    conn.execute("""create table seed (
      name text primary key not null)""")

    conn.execute("""create table ignore (
      name text primary key not null)""")
   
    conn.execute("""create table ban (
      name text primary key not null)""")
   
    # used to keep track of read messages
    conn.execute("""create table dm (
      id text primary key not null)""")
    
    conn.execute("""create table reply (
      id text primary key not null,
      tweet text not null,
      stars int)""")

    conn.commit()
    conn.close()

def save_source(conn, post):
    conn.execute("""insert or ignore into source (source, imgurl)
                    values (?, ?)""", (post['source'], post['imageurl']))

    for aspect in post['aspects']:
        # these are not checked for changes, so just insert if necessary
        conn.execute("""insert or ignore into source_aspect (source, aspect)
                        values (?, ?)""", (post['source'], aspect))

def save_tweet(conn, post):
    # note this does an update first, then an insert that ignores failure
    # this way if it exists it's updated, and if it doesn't exist it's left alone
    conn.execute("""update tweet set faves = ?, rts = ? where tweetid = ?""", 
            (post['faves'], post['rts'], post['id']))
    conn.execute("""insert or ignore into tweet (faves, rts, source, tweetid)
                    values (?, ?, ?, ?) """,
            (post['faves'], post['rts'], post['source'], post['id']))

def load_aspects():
    model = {
            'scores': defaultdict(Counter), 
            'postcounts': defaultdict(Counter), 
            'perpost': Counter()}
    timeline = twitter.statuses.user_timeline(screen_name=bot_name,count=200)

    conn = sqlite3.connect('showme.db')
    tweetmap = {}
    for tweet in timeline:
        tweetmap[tweet['id_str']] = {
                'rts': int(tweet['retweet_count']),
                'faves': int(tweet['favorite_count'])}
        save_tweet(conn, {'id': tweet['id_str'], 'rts': tweet['retweet_count'], 'faves':tweet['favorite_count'], 'source':''})
    conn.commit()
    conn.close()

    ids = [] # the source urls, used to prevent duplicates
    post_counts = Counter() # how many posts is each aspect used on?

    conn = sqlite3.connect('showme.db')
    seeds = [s[0] for s in conn.execute("select name from seed").fetchall()]
    for seed in seeds:
        model['scores']['tag'][seed] = seed_val
    ignorelist = [t[0] for t in conn.execute("select name from ignore").fetchall()]
    ignorelist = frozenset(ignorelist)

    tweetbonus = Counter()
    for tweetid, stars in conn.execute("select tweet, stars from reply"):
        tweetbonus[tweetid] += stars

    cur = conn.cursor()
    for source in cur.execute("""select source from source""").fetchall():
        source = source[0]
        ids.append(source)

        tweet = cur.execute("select faves, rts, tweetid from tweet where source = ?", (source,)).fetchone()

        post_aspects = list(cur.execute("select aspect from source_aspect where source = ?", (source,)))
        aspect_count = len(post_aspects)

        for aspect in post_aspects:
            aspect = aspect[0]
            post_counts[aspect] += 1
            field, _, val = aspect.partition(':')
            model['postcounts'][field][val] += 1
            if tweet:
                fav_count = tweet[0] + tweetbonus[tweet[2]]
                model['scores'][field][val] += int((fav_val * fav_count) + (rt_val * tweet[1]) / aspect_count)

    for field in model['scores']:
        for val in list(model['scores'][field].keys()):
            aspect = field + ':' + val
            # The minimum post count is effectively ten to avoid over-valuing aspects
            # Note that the real post count can be 0, as for seeds
            base = max(10, post_counts[aspect])
            model['perpost'][aspect] = int(model['scores'][field][val] / base)
            if model['scores'][field][val] < threshold:
                # don't consider tags with less than some number of likes
                del model['scores'][field][val]
                del model['perpost'][aspect]
            if field == 'liked' or field == 'reblog':
                # these fields are not used to select things
                del model['perpost'][aspect]
                continue
            if val in ignorelist:
                # ignored things are bad pickers
                del model['perpost'][aspect]

    conn.commit()
    conn.close()
    
    if justranking:
        # TODO redo this

        sys.exit(0)

    return (ids, model)

def counter_choice(aspects,debug=False):
    # pick weighted random aspect, use it for search

    total = sum(aspects.values())
    pick = randint(0, total)
    for aspect, count in aspects.items():
        pick -= count
        if pick < 0:
            return aspect

def pick_by_score(results, model):
    if not results: return None # in case it's empty
    scoremap = Counter({p['post_url']:0 for p in results})
    aspects = model['scores']['tag'] + model['scores']['liked']

    # get avg for post
    for result in results:
        url = result['post_url']
        if 'score' in result:
            scoremap[url] += result['score']
        for tag in result['tags']:
            scoremap[url] += aspects[tag]

            # This is effectively a large penalty to all unknown tags
            if tag in aspects:
                scoremap[url] += 10000

        # bonus points for trusted likers
        if 'liked_by' in result:
            for liker in result['liked_by']:
                scoremap[url] += aspects['liked:' + liker]

        scoremap[url] = int(scoremap[url] /  (len(result['tags']) + 1) )

    candidates = Counter()
    for key, val in scoremap.most_common():
        candidates[key] = val
        if nopost:
            match = None
            for res in results:
                if res['post_url'] == key:
                    match = res
            print(str(val) + '\t' + str(key) + '\t' + match['origin'])
    if nopost:
        print(len(scoremap))
        sys.exit(0)

    picked = counter_choice(candidates)
    for res in results:
        if res['post_url'] == picked: 
            res['score'] = scoremap[picked]
            return res
    return None

def flickr_get_tag(tag):
    if not 'flickr' in KEYS: return [] 
    out = requests.post('https://api.flickr.com/services/rest/', {
        'nojsoncallback': 1,
        'method': 'flickr.photos.search',
        'api_key': KEYS['flickr'], 
        'tags': tag, 
        'extras': 'owner_name,tags,views,count_faves',
        'license': '1,2,4,5,7,8', 
        'format':'json'}).json()['photos']['photo']
    out = [o for o in out if int(o['count_faves']) > 50]

    # take only the top portion
    out.sort(key=lambda o: o['count_faves'],reverse=True)
    cutoff = max(10,int(len(out)/4))
    out = out[:cutoff]

    for o in out:
        o['score'] = 5000
        o['post_url'] = 'https://www.flickr.com/{}/{}'.format(o['owner'], o['id'])
        o['tags'] = o['tags'].split(' ')
        o['type'] = 'photo'
        o['blog_name'] = 'flickr:' + o['owner']
        o['origin'] = '#' + ''.join(tag.title().split(' '))
        o['origin'] = 'tag:' + tag
        if not tag in o['tags']:
            o['tags'].append(tag)
        o['flickr'] = True
    return out

def tumblr_get_tag(tag):
    year = 365 * 24 * 60 * 60
    baseurl = 'https://api.tumblr.com/v2/tagged?feature_type=everything&reblog_info=true&notes_info=true&filter=text&tag=' + tag + '&api_key=' + KEYS['tumblr']
    out = requests.get(baseurl).json()['response']
    if out:
        out += requests.get(baseurl + '&before=' + str(out[-1]['timestamp'])).json()['response']
    out = [o for o in out if o['note_count'] > 20]

    # take only the top portion
    out.sort(key=lambda o: o['note_count'],reverse=True)
    cutoff = max(10,int(len(out)/4))
    out = out[:cutoff]
    
    for c in out:
        c['score'] = 5000
        if not tag in c['tags']:
            c['tags'].append(tag)

        # some blogs use their name as a tag on everything, stop that
        if c['blog_name'] in c['tags']:
            c['tags'].remove(c['blog_name'])
        # if this is a reblog, the original author is an author too
        if 'reblog' in c:
            c['original_author'] = [r['blog']['name'] for r in c['trail']]
        # save reblog/like info to use in ranking
        if 'notes' in c:
            c['reblog_sources'] = [r['blog_name'] for r in c['notes'] if r['type'] == 'reblog']
            c['liked_by'] = [l['blog_name'] for l in c['notes'] if l['type'] == 'like']
        c['origin'] = 'tag:' + tag
    return out

def flickr_get_author(author):
    if not 'flickr' in KEYS: return [] 
    parts = author.split(':')
    if len(parts) < 2 or not parts[0] == 'flickr': return []

    out = requests.post('https://api.flickr.com/services/rest/', {
        'nojsoncallback': 1,
        'method': 'flickr.photos.search',
        'api_key': KEYS['flickr'], 
        'user_id': parts[1], 
        'extras': 'owner_name,tags',
        'license': '1,2,4,5,7,8', 
        'format':'json'}).json()['photos']['photo']

    for o in out:
        o['post_url'] = 'https://www.flickr.com/{}/{}'.format(o['owner'], o['id'])
        o['tags'] = o['tags'].split(' ')
        o['type'] = 'photo'
        o['score'] = 5000
        o['note_count'] = 1000 # flickr photos are pretty good
        o['blog_name'] = 'flickr:' + o['owner']
        o['origin'] = o['blog_name']
        o['flickr'] = True
    return out

def tumblr_get_author(author):
    if author.split(':')[0] == 'flickr': return [] # we can't handle this
    baseurl = 'https://api.tumblr.com/v2/blog/' + author + '/posts/photo?filter=text&reblog_info=true&notes_info=true&api_key=' + KEYS['tumblr']
    candidates = requests.get(baseurl).json()['response']['posts']
    candidates += requests.get(baseurl + '&offset=20').json()['response']['posts']

    for c in candidates:
        c['origin'] = 'author:' + author
        c['score'] = 5000
        if 'reblog' in c:
            c['original_author'] = [r['blog']['name'] for r in c['trail']]
        # likes are considered partial authors worth exploring
        if 'notes' in c:
            reblogs = [r['blog_name'] for r in c['notes'] if r['type'] == 'reblog']
            c['liked_by'] = [l['blog_name'] for l in c['notes'] if l['type'] == 'like']
            c['reblog_sources'] = uniq(c['reblog_sources'] + reblogs)

    return candidates

def flickr_get_pool(poolid):
    res = requests.post('https://api.flickr.com/services/rest/', {
        'nojsoncallback': 1,
        'method': 'flickr.photos.search',
        'api_key': KEYS['flickr'], 
        'group_id': poolid,
        'extras': 'owner_name,tags',
        'license': '1,2,4,5,7,8', 
        'format': 'json'}).json()

    # seems auth randomly fails sometimes
    if not 'photos' in res:
        return []
    
    out = res['photos']['photo']

    for o in out:
        o['post_url'] = 'https://www.flickr.com/{}/{}'.format(o['owner'], o['id'])
        o['tags'] = o['tags'].split(' ')
        o['type'] = 'photo'
        o['score'] = 5000
        o['note_count'] = 1000 # flickr photos are pretty good
        o['blog_name'] = 'flickr-pool:' + poolid
        o['origin'] = o['blog_name']
        o['flickr'] = True

    return out

def gather_candidates(aspects):
    candidates = []
    aspects_c = Counter(aspects) # make a copy to mutate
    for ii in range(0, min(10, len(aspects_c))):
        del aspects_c[aspect] # this way we can't pick the same thing twice
        aspect = counter_choice(aspects_c)
        if nopost: print(aspect)
        form, _, val = aspect.partition(':')
        if form == 'tag':
            try:
                candidates += tumblr_get_tag(val)
            except:
                pass
            candidates += flickr_get_tag(val)
        elif form == 'author':
            try:
                candidates += tumblr_get_author(val)
            except:
                pass
            candidates += flickr_get_author(val)
        elif form == 'flickr-pool':
            candidates += flickr_get_pool(val)
    return candidates

def remove_duplicates(candidates, ids):
    # The source URL is used when the image comes from an external source
    # Hopefully making use of it will help prevent duplicates
    for r in candidates:
        r['orig_url'] = r['post_url']

    # filter to only photo posts
    candidates = [r for r in candidates if r['type'] == 'photo']
    # no duplicates
    candidates = [r for r in candidates if not r['post_url'] in ids]
    candidates = [r for r in candidates if not r['orig_url'] in ids]
    return candidates

def remove_banned(candidates):
    # no banned blogs
    conn = sqlite3.connect('showme.db')
    banned = [t[0] for t in conn.execute("select name from ban").fetchall()]
    conn.close()
    candidates = [r for r in candidates if not r['blog_name'] in banned]
    return candidates

def choose_post(ids, model):
    # pick random search result, avoiding duplicates
    candidates = gather_candidates(model['perpost'])
    candidates = remove_duplicates(candidates, ids)
    candidates = remove_banned(candidates)

    # If we have nothing break out and try again
    if not candidates:
        return False

    choice = pick_by_score(candidates, model) 
    return choice

def make_post(source):
    post = {
            'source': source['post_url'], 
            'score': source['score'], 
            'id': 'null', 
            'origin': source['origin']}
    post['aspects'] = [ ('tag:' + t.lower()) for t in source['tags']] + ['author:' + source['blog_name']]

    if 'flickr' in source:
        # This is very irritating.
        # Flickr supports originals too large for Twitter to accept the upload.
        # They offer other sizes, but, for old images sometimes there's not actually an image.
        sizes = requests.post('https://api.flickr.com/services/rest/', {
            'nojsoncallback': 1,
            'method': 'flickr.photos.getSizes',
            'api_key': KEYS['flickr'], 
            'photo_id': source['id'], 
            'format':'json'}).json()['sizes']['size']
        size = sizes[-1]
        if int(size['width']) > 2000 or int(size['height']) > 2000:
            size = sizes[-2]
        post['imageurl'] = size['source']
        imageurl = post['imageurl']
        # get pools as possible sources for future posts
        res = requests.post('https://api.flickr.com/services/rest/', {
            'nojsoncallback': 1,
            'method': 'flickr.photos.getAllContexts',
            'api_key': KEYS['flickr'],
            'photo_id': source['id'],
            'format': 'json'}).json()
        
        if 'pool' in res:
            for group in res['pool']:
                post['aspects'].append('flickr-pool:' + group['id'])
    
    if not 'flickr' in source: 
        # at the moment, this implies Tumblr
        # Should be cleaned up and made generic...
        if 'reblog_sources' in source:
            for rs in source['reblog_sources']:
                post['aspects'].append('reblog:' + rs)
        if 'liked_by' in source:
            for ll in source['liked_by']:
                post['aspects'].append('liked:' + ll)
        if 'original_author' in source:
            for ll in source['original_author']:
                post['aspects'].append('author:' + ll)

        imageurl = source['photos'][0]['original_size']['url']
        post['imageurl'] = imageurl
        post['text'] = source['caption'][:100]
        if len(source['caption']) > 100:
            post['text'] += '...'

     
    image_fname = imageurl.split('/')[-1]
    fname = path + '/out/' + image_fname
    response = requests.get(imageurl, stream=True)
    with open(fname, 'wb') as out_file:
        shutil.copyfileobj(response.raw, out_file)

    # This is for Tumblr - international URLs confusing and get partially treated as text
    # this attracts spam bots looking for keywords
    status = '/'.join(post['source'].split('/')[0:5])
    print(json.dumps(post, ensure_ascii=False,sort_keys=True))
    filedata = None
    with open(fname, 'rb') as imagefile:
        filedata = imagefile.read()

    if nopost: sys.exit(0) # just wanted to see what would have been posted

    params = {"media[]": filedata, "status": status}
    resp = twitter.statuses.update_with_media(**params)

    post['id'] = resp['id_str']
    
    # initial values
    post['faves'] = 0
    post['rts'] = 0

    conn = sqlite3.connect('showme.db')
    save_source(conn, post)
    save_tweet(conn,post)
    conn.commit()
    conn.close()

def process_commands():
    """Read in direct messages and act on them if necessary."""
    # strategy: 
    # - get new dms
    # - save dms into db
    # - get unprocessed dms from db, ordered by time, and apply
    # commands: key (flickr/tumblr), seed (tag/author), ignore (tag) 
    # should return seed and ignore list
    messages = twitter.direct_messages()
    conn = sqlite3.connect('showme.db')
    read = [m[0] for m in conn.execute("select id from dm").fetchall()]
    for message in messages:
        # we don't see our own replies here, so only check to see if we're following them
        if not message['sender']['following']: continue
        if message['id_str'] in read: continue # read already

        words = message['text'].split(' ')
        term = ' '.join(words[1:])

        if words[0] == 'key':
            if len(words) != 3: twitter.direct_messages.new(text="format is wrong; use : key <service> <key>", user_id=message['sender']['id'])
            conn.execute("insert or replace into key (service, key) values (?,?)", (words[1], words[2]))
            twitter.direct_messages.new(text="ok", user_id=message['sender']['id'])
        elif words[0] == 'seed':
            conn.execute("insert or replace into seed (name) values (?)", (term, ))
            twitter.direct_messages.new(text="ok, seeded '{}'".format(term), user_id=message['sender']['id'])
        elif words[0] == 'unseed':
            conn.execute("delete from seed where name = ?", (term, ))
            twitter.direct_messages.new(text="ok, unseeded '{}'".format(term), user_id=message['sender']['id'])
        elif words[0] == 'ignore':
            conn.execute("insert or replace into ignore (name) values (?)", (term, ))
            twitter.direct_messages.new(text="ok, ignored '{}'".format(term), user_id=message['sender']['id'])
        elif words[0] == 'unignore':
            conn.execute("delete from ignore where name = ?", (term, ))
            twitter.direct_messages.new(text="ok, unignored '{}'".format(term), user_id=message['sender']['id'])
        elif words[0] == 'ban':
            conn.execute("insert or replace into ban (name) values (?)", (term, ))
            twitter.direct_messages.new(text="ok, banned '{}'".format(term), user_id=message['sender']['id'])
        elif words[0] == 'unban':
            conn.execute("delete from ban where name = ?", (term, ))
            twitter.direct_messages.new(text="ok, unbanned '{}'".format(term), user_id=message['sender']['id'])
        else: 
            twitter.direct_messages.new(text="I don't understand. Valid commands: key, seed, ignore, ban", user_id=message['sender']['id'])
        conn.execute("insert or replace into dm (id) values (?)", (message['id_str'], ))
        conn.commit()
    conn.close()

def load_keys():
    conn = sqlite3.connect('showme.db')
    for service, key in conn.execute("select service, key from key").fetchall():
        KEYS[service] = key
    conn.close()
    if not ('flickr' in KEYS or 'tumblr' in KEYS):
        print("No api keys, giving up")
        sys.exit(1)

def process_replies():
    """Read replies"""
    # replies can use emoji. If it's from a user we follow, they can boost posts this way.
    replies = twitter.statuses.mentions_timeline()
    conn = sqlite3.connect('showme.db')
    read = [m[0] for m in conn.execute("select id from reply").fetchall()]
    for reply in replies:
        if reply['id_str'] in read: continue # already done
        if not reply['user']['following']: continue
        if not reply['in_reply_to_status_id_str']: continue # we're only interested in specific replies
        
        bonus = 0
        for cc in reply['text']:
            # this is an emoji star, should probably add other characters
            if cc in '⭐🌟': bonus += 1

        conn.execute("insert or replace into reply (id, tweet, stars) values (?,?,?)",
                (reply['id_str'], reply['in_reply_to_status_id_str'], bonus))
        conn.commit()
        # favorite it to let them know we saw it
        twitter.favorites.create(_id=reply['id_str'])
    conn.close()

def main():

    if doinitdb:
        # this needs to be done once the first time it's run
        # alternate strategy: do automatically if db file doesn't exist
        init_db()
        sys.exit(0)

    process_commands() # commands via dm from the operator
    process_replies() # replies to add extra points
    load_keys() # get API keys so we can fetch posts

    ids, model = load_aspects() # load tag/author/etc data from db

    source = False
    while not source:
        source = choose_post(ids, model) # the main selection part

    make_post(source) # handles twitter post & saving

if __name__ == "__main__":
    main()
