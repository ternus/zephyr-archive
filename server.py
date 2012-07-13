from flask import *
# flask-peewee bindings
from flask_peewee.db import Database
from peewee import *
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
def hello_world():
    classes = ZClass.select().order_by(('name', 'asc'))
    return render_template('classes.html', classes=classes)

@zarchive.route('/<cls>')
def zclass(cls):
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 100))
    zephyrs = Zephyr.select().order_by(('time', 'desc')).paginate(page, per_page)
    return render_template('zephyrs.html', zephyrs=zephyrs)

@zarchive.route('/sub/<cls>')
def sub(cls):
    subbed = not ZClass.exists(name=cls)
    if not subbed:
        zc = ZClass.create(name=cls)
    return render_template('sub.html', subbed=subbed)

def listen_for_zephyrs():
    subs = zephyr.Subscriptions()
    for z in ZClass.select():
        subs.add((z.name, '*', '*'))
    count = ZClass.select().count()
    print "Listening for zephyrs (%s current subs)..." % count
    while True:
        nz = zephyr.receive(block=True)
        sender = nz.sender.replace("@ATHENA.MIT.EDU", "")
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
            ZClass.get_or_create(name=sender)

if __name__ == '__main__':
    create_tables()
    pid = os.fork()
    if pid == 0:
        listen_for_zephyrs()
    else:
        zarchive.run()
