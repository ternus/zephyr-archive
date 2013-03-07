from flask import *
# flask-peewee bindings
from flask_peewee.db import Database
from peewee import VarCharColumn
from peewee import *
from flask.ext.cache import Cache
import datetime
import os, sys, time
import zephyr
import subprocess
DEBUG = False
SECRET_KEY = 'sekrit keeey'
PROMISCUOUS_MODE = True # Otherwise known as 'goodell mode.'  
                        # Subscribe to the classes of everyone we see.
# configure our database
DATABASE = 'example.db'
CHECK_TIMEOUT = 600

from localsettings import *

zarchive = Flask(__name__)
#cache = Cache(zarchive, config={'CACHE_TYPE':'simple'})
zarchive.config.from_object(__name__)

#database = SqliteDatabase(DATABASE, check_same_thread=False)
database = PostgresqlDatabase(DATABASE, host='localhost', user=DATABASE_USER, password=DATABASE_PASSWORD)

class BaseModel(Model):
    class Meta:
        database = database

class ZClass(BaseModel):
    name = PrimaryKeyField(column_class=VarCharColumn)

    def un_level(self):
        n = self.name
        level = 0
        while n.startswith('un'):
            level += 1
            n = n[2:]
        return level

class ZUser(BaseModel):
    name = PrimaryKeyField(column_class=VarCharColumn)

class ZSub(BaseModel):
    zuser = ForeignKeyField(ZUser)
    zclass = ForeignKeyField(ZClass)
    first_seen = DateTimeField(default=datetime.datetime.now)
    last_spoke = DateTimeField(default=datetime.datetime.now)
    
class Zephyr(BaseModel):
    uid = PrimaryKeyField(column_class=VarCharColumn)
    sender = ForeignKeyField(ZUser)
    zclass = ForeignKeyField(ZClass)
    instance = CharField()
    zsig = CharField()
    message = TextField()
    time = DateTimeField(default=datetime.datetime.now)        

def create_tables():
    ZClass.create_table(fail_silently=True)
    ZUser.create_table(fail_silently=True)
    ZSub.create_table(fail_silently=True)
    Zephyr.create_table(fail_silently=True)

#@cache.cached(timeout=300)
def users():
    return ZUser.select().order_by(('name', 'asc')).annotate(Zephyr).order_by(('count', 'desc'))

#@cache.cached(timeout=300)
def classes():
    return ZClass.select().order_by(('name', 'asc')).annotate(Zephyr).order_by(('count', 'desc')).annotate(Zephyr, Max('uid', 'max_id'))

def last():
    return list(Zephyr.select().order_by(('time', 'desc')).limit(1))[0].time

@zarchive.route('/')
def all_classes():
    return render_template('classes.html', classes=classes(), users=users(), last=last())

@zarchive.route('/class/<cls>')
def zclass(cls):
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 100))
    startdate = request.args.get('startdate')
    enddate = request.args.get('enddate')
    instance = request.args.get('instance', None)
    zephyrs = Zephyr.filter(zclass=cls)
    if startdate:
        try:
            zephyrs = zephyrs.filter(time>=startdate)
        except:
            pass
    if enddate:
        try:
            zephyrs = zephyrs.filter(time<=enddate)
        except:
            pass
    if instance:
        try:
            zephyrs = zephyrs.filter(instance=instance)
        except:
            pass
    zephyrs = zephyrs.order_by(('time', 'desc')).paginate(page, per_page)
    zephyrs = list(zephyrs)
    zephyrs.reverse()
    return render_template('zephyrs.html', zephyrs=zephyrs, page=page, per_page=per_page)

# TODO Refactor this into something sensible.

@zarchive.route('/user/<user>')
def zuser(user):
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 100))
    zephyrs = Zephyr.filter(sender=user).order_by(('time', 'desc')).paginate(page, per_page)
    return render_template('zephyrs.html', zephyrs=zephyrs)

@zarchive.route('/sub/<cls>')
def sub(cls):
    subbed = ZClass.filter(name=cls).exists()
    if not subbed:
        zc = ZClass.create(name=cls)
    return render_template('subbed.html', subbed=subbed, there=cls)

def listen_for_zephyrs():
    subs = zephyr.Subscriptions()
    count = ZClass.select().count()
    print "Subscribing to zephyrs (%s current subs)..." % count
    for z in ZClass.select():
	try:
            subs.add((z.name, '*', '*'))
            subs.add(('un%s' % z.name, '*', '*'))
            subs.add(('unun%s' % z.name, '*', '*'))
	except Exception, e:
	    print "Failed to sub to %s (%s)" % (z.name, e)
    print "Listening for zephyrs (%s current subs)..." % count
    while True:
        nz = zephyr.receive(block=True)
        if nz.cls.lower() == 'message' and nz.instance.lower() == 'personal': continue
        try:
            sender = nz.sender.replace("@ATHENA.MIT.EDU", "")
            print "[%s] Class: %s Instance: %s Sender: %s" % (str(datetime.datetime.now()), nz.cls, nz.instance, sender)
            zclass = ZClass.get_or_create(name=nz.cls)
            zuser = ZUser.get_or_create(name=sender)
            zsub = ZSub.get_or_create(zuser=sender, zclass=nz.cls)
            zsub.last_spoke = datetime.datetime.now()
            zsub.save()
            zephyr_obj = Zephyr.get_or_create(
                uid = nz.uid.time,
                sender = sender,
                zclass = nz.cls.decode('utf-8'),
                instance = nz.instance.decode('utf-8'),
                zsig = nz.fields[0].decode('utf-8'),
                message = nz.fields[1].decode('utf-8'))
            database.commit()
            # Check to see if we've added subs out-of-band.
            # XXX This won't take effect until the next time we
            # XXX receive a zephyr.
            if ZClass.select().count() != count:
                for z in ZClass.select():
                    subs.add((z.name, '*', '*'))
                    subs.add(('un%s ' % z.name, '*', '*'))
                print "Got %s new subs" % (ZClass.select().count() - count)
                count = ZClass.select().count()
                database.commit()
            if PROMISCUOUS_MODE:
                # New person?  Subscribe to their personal class.
                if not ZClass.filter(name=sender).exists():
                    print "Found new person -- subscribing to %s" % sender        
                    ZClass.create(name=sender)
        except Exception, e:
            print "Error receiving zephyr to %s from %s: %s" % (nz.cls, sender, e)

def zwrite(message):
    return subprocess.call('zwrite -d -c ternus-test -m "%s"' % message, shell=True)

def monitor_uptime():
    up = True
    notified = False
    lz = last()
    while True:
        print "[%s] Checking: " % datetime.datetime.now(), 
        new_lz = last()
        if new_lz == lz:
            if up:
                zwrite("Probably down, Last zephyr received at %s" % last())
                up = False
                notified = False
            else:
                if not notified:
                    subprocess.call('zwrite -d ternus -m "zarchive down!"', shell=True)
                    notified = True
                print "... still down"
        elif not up:
            zwrite("Back up!")
            up = True
        else:
            print "Check OK"
        lz = new_lz
        print ""
        time.sleep(CHECK_TIMEOUT)


if __name__ == '__main__':
    database.connect()
    if sys.argv[1] == 'serve':
        zarchive.run(host='0.0.0.0')
    elif sys.argv[1] == 'listen':
        listen_for_zephyrs()
    elif sys.argv[1] == 'check':
        monitor_uptime()
