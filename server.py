from flask import *
# flask-peewee bindings
from flask_peewee.db import Database
from peewee import VarCharColumn
from peewee import *
import datetime
import os
import zephyr

SECRET_KEY = 'sekrit keeey'
PROMISCUOUS_MODE = True # Otherwise known as 'goodell mode.'  
                        # Subscribe to the classes of everyone we see.
# configure our database
DATABASE = 'example.db'
DEBUG = True

zarchive = Flask(__name__)
zarchive.config.from_object(__name__)

database = SqliteDatabase(DATABASE, check_same_thread=False)

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

@zarchive.route('/')
def all_classes():
    classes = ZClass.select().order_by(('name', 'asc')).join(Zephyr, 'left outer').annotate(Zephyr).order_by(('count', 'desc'))
    users = ZUser.select().order_by(('name', 'asc')).join(Zephyr, 'left outer').annotate(Zephyr).order_by(('count', 'desc'))
    return render_template('classes.html', classes=classes, users=users)

@zarchive.route('/class/<cls>')
def zclass(cls):
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 100))
    zephyrs = Zephyr.filter(zclass=cls).order_by(('time', 'desc')).paginate(page, per_page)
    return render_template('zephyrs.html', zephyrs=zephyrs)

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
    for z in ZClass.select():
        subs.add((z.name, '*', '*'))
    count = ZClass.select().count()
    print "Listening for zephyrs (%s current subs)..." % count
    while True:
        nz = zephyr.receive(block=True)
        if nz.cls.lower() == 'message' and nz.instance.lower() == 'personal': continue
        try:
            sender = nz.sender.replace("@ATHENA.MIT.EDU", "")
            print "New zephyr to -c %s from %s" % (nz.cls, sender)
            zclass = ZClass.get_or_create(name=nz.cls)
            zuser = ZUser.get_or_create(name=sender)
            zsub = ZSub.get_or_create(zuser=sender, zclass=nz.cls)
            zsub.last_spoke = datetime.datetime.now()
            zsub.save()
            zephyr_obj = Zephyr.get_or_create(
                uid = nz.uid.time,
                sender = sender,
                zclass = nz.cls,
                instance = nz.instance,
                zsig = nz.fields[0],
                message = nz.fields[1])

            # Check to see if we've added subs out-of-band.
            if ZClass.select().count() != count:
                for z in ZClass.select():
                    subs.add((z.name, '*', '*'))
                print "Got %s new subs" % (ZClass.select().count() - count)
                count = ZClass.select().count()

            if PROMISCUOUS_MODE:
                # New person?  Subscribe to their personal class.
                if not ZClass.filter(name=sender).exists():
                    print "Found new person -- subscribing to %s" % sender        
                    ZClass.create(name=sender)
        except:
            print "Error receiving zephyr from %s to %s" % (nz.cls, sender)

if __name__ == '__main__':
    create_tables()
    pid = os.fork()
    if pid == 0:
        listen_for_zephyrs()
    else:
        zarchive.run(host='0.0.0.0')
