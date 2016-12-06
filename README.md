# showmemore

**ShowMeMore** is an automated researcher. Given a list of tags to start with,
it goes hunting for images, and over time grows its model in response to
reactions, slowly reaching out to find things you weren't aware you already
liked. 

It started as an attempt to recreate
[@Archillect](https://twitter.com/archillect); you can read more about how it
came to be and the motivations behind it
[here](https://www.dampfkraft.com/by-id/2931e31b.html#The-Laser-Syriacum). 

Currently, it's configured to be run as a Twitter bot pulling images from
Tumblr and Flickr. 

## Setting up Your Own

Currently setting up your own bot involves a lot of manual steps; I cannot
pretend it is anything but tedious. Before getting started you should be
familiar with concepts like API keys and have at least a little experience in
the Unix shell. (If someone wants to automate more of this it would be much
appreciated.)

While the technical steps don't take a lot of time, you'll need to spend a
while evaluating early posts to nudge your bot in the right direction, which
might take a few days. 

### Create a bot account

Create a Twitter account for the bot to use. I would be flattered if you called
it `showme<something>`, but anything will do.

Have the account follow your main Twitter account; you'll send DMs to control
it after it's running. 

It's fine to make the account private; in fact, I would recommend keeping it
private until you make sure the posts are what you're going for.

You should tweet once via the web client so Twitter knows a human is fiddling
with the account.

### Get API Keys

You need to use at least one of Flickr or Tumblr as a source for posts.

You can register a Tumblr API key
[here](https://www.tumblr.com/docs/en/api/v2). They will give you two API keys;
the one you care about is your "OAuth Consumer Key". We'll use it later, so
just copy it somewhere for now.

You can register a Flickr API key
[here](https://www.flickr.com/services/api/misc.api_keys.html). Flickr will
also give you two keys; you'll need the longer one.

You also need a Twitter app, which you can register
[here](https://apps.twitter.com/). The app will need to request permission to
read and send DMs, which is not the default setting, so be sure to specify that.

### Set up the bot's environment

You'll need to clone the repository and perform a few more steps. You need
**Python 3** installed. The only library dependencies are
[requests](http://docs.python-requests.org/en/master/) and
[twitter](https://github.com/sixohsix/twitter).

    git clone git@github.com:polm/showmemore.git
    cd showmemore
    pip install -r requirements.txt
    echo mybot > name # use your bot's Twitter handle instead of "mybot"
    mkdir out # downloaded images will be saved here

You'll need to stash your Twitter App credentials in the directory for the bot
to get. `twitter-creds.json` should be a JSON file with `key` and `secret`
fields, as indicated by your Twitter app info.

At this point, have a browser open and logged in to Twitter as your bot. We're
going to connect the application to the account. Run the script like this:

    ./laser.py initdb

This will do a couple of things. First it may open a web browser, possibly in
your terminal; kill that and a Twitter URL will be displayed. Open that while
logged in as the bot account, authorize the application, and post the numeric
code you get into your terminal. After that it will initialize the database,
and you're almost ready to go.

### Initial Settings

Using your normal Twitter account - the one the bot is following - it's time to
give the bot some information to get started with. The bot recognizes several commands:

- **key**: Set an API key for a source service. Currently, valid service names are just `flickr` and `tumblr`. Example: `key flickr [your api key]` 
- **seed**: Assign points to a tag, used to get the bot started. Example: `seed some cool tag`
- **ignore**: Don't use the given tag to pick posts. (Posts with the tag won't be banned, but it'll never be used as a starting point to look for candidates.) Example: `ignore some bad tag`
- **ban**: Ban posts from a Tumblr blog. The "blog name" is usually the `example` in `example.tumblr.com`. Alternately, to ban a Flickr user, use the format `flickr:[user-id]`, where the `user-id` is the automatically assigned Flickr user ID (looks like `12345678@N00`, not a normal username). Posts from a banned blog will never be selected.

The `seed`, `ignore`, and `ban` keywords can be prefixed with `un` to undo
them. Don't quote arguments to commands, it'll just confuse the bot. For Tumblr
tags, use spaces or dashes the same way Tumblr blogs do - the API treats them
the same, but it's better to use the more common form for seeding or ignoring
to avoid confusing the bot.

To get started you should set at least one API key and at least five seeds. I'd
also go ahead and ignore a few overly general tags, like `art`, `gif`,
`tumblr`, and `ifttt`.

### Set up cron

We're almost done. The script needs to be run repeatedly in order to post.
Here's an example cron entry to run it every ten minutes:

    */10 * * * * /home/you/code/showmemore/post.sh

The `post.sh` script just handles logging and encoding. Try running it manually
once to be sure everything works. The bot should reply to each DM you've sent
to let you know it was processed. If it posts successfully, it will add a line
to the `log` file in its script directory consisting of JSON that describes the
post. One field in this JSON to look out for is `origin` - while every aspect
of a candidate is judged, the `origin` is the aspect that was used to find the
candidate in the first place. Checking the origin is a good way to understand
what's going on when the bot surprises you.

### Training the bot

At this point the bot should be running successfully, but it doesn't have much
of a model to go on. My suggestion would be to let the bot post ten or twenty
items, then favorite the ones that match your image of what the bot should
post. This will give it more potential sources to draw from when posting. After
that watch it for a day or two, favoriting good posts and building up your
ignore list, to guide it to what you want it to be. 

If you don't like cluttering up your favorites list, use the bot to favorite
its own posts. You can also reply to posts from any account the bot follows and
every emoji star (⭐) will be counted as an extra like; you'll know it worked
if the post is automatically favorited.

Good luck, and have fun!

## Algorithm Overview

The algorithm for selecting posts is simpler than you might think. It doesn't
use anything you'd describe as artificial intelligence, and the actual visual
properties of candidate images are never considered. Its lack of sophistication
means it falls down spectacularly sometimes, but it does have some advantages -
calculations are fast and don't require large banks of data. 

Overall, the algorithm is a bit like Pagerank working on photo metadata. 

"Aspects" are true binary properties of a post - tags and authors (or at least
source blogs) are the most important aspects, but liking or reblogging users on
Tumblr and photo groups on Flickr are also aspects. Aspects have a type such as
`tag`, `author`, `reblog`, `liked`, `flickr-pool`, and a value that identifies
the relevant resource.

When a tweet by the bot is liked, that's treated as a vote for every aspect of
the source post. (RTs are just treated as multiple likes for scoring purposes.)
Votes are used to calculate two kinds of scores: all-time historical score and
per-post score. So if an aspect has been present in 10 posts that have together
gotten 500 likes, it might have an all-time score of 500, but a per-post score
of just 50. 

In actuality, it's a little more complicated than that - points a tweet gets
are divided equally between all aspects on the tweet. So a tweet with a source
with many tags will give fewer points to each.

Anyway, regarding how points are used, the algorithm has three phases:

1. Candidate Gathering
2. Culling
3. Post Selection

In **Candidate Gathering**, **per-post** scores are used to make a series of
weighted random picks of aspects. These aspects are used to query source APIs
and get posts to look at. 

In **Culling**, items that have been posted before or are from banned blogs are
removed from the candidate list. This is the simplest phase, but it's important
to keep the bot from going in circles. How to determine if two posts are
duplicates is also a bit subtle; the current design errs on the side of posting
duplicates sometimes while being simple in implementation. 

If no candidates are left at the end of culling, the algorithm returns to the
Candidate Gathering phase. Otherwise, it proceeds to Post Selection.

In **Post Selection**, candidates are scored for all their aspects based on
**all-time** aspect scores. Then the highest-scoring post is made into a tweet,
and the aspects attached to the post are recorded in the application's
database.

These three steps are repeated every time the script is run.

## Next Steps

See the issues page for small things.

A bigger change that would be nice would be generalizing the program to work on
webpages rather than Tumblr and Flickr API items, as a kind of guided Pagerank. 

## License

Kopyleft, All Rites Reversed, do as you please. WTFPL if you prefer.

-POLM
