import time
import datetime

from zope.interface import implements
import sqlalchemy as sql

from moai.interfaces import IDatabase

class SQLiteDatabase(object):
    """Sqlite implementation of a database backend
    This implements the :ref:`IDatabase` interface, look there for
    more documentation.
    """
    implements(IDatabase)

    def __init__(self, dbpath=None, mode='w'):
        self.db = self._connect(dbpath)
        self.records = self.db.tables['records']
        self.metadata = self.db.tables['metadata']

    def _connect(self, dbpath):
        if dbpath is None:
            dburi = 'sqlite:///:memory:'
        else:
            dburi = 'sqlite:///%s' % dbpath
            
        engine = sql.create_engine(dburi)
        db = sql.MetaData(engine)


        sql.Table('records', db,
                  sql.Column('record_id', sql.Integer, primary_key=True),
                  sql.Column('name', sql.Unicode, unique=True, index=True),
                  sql.Column('when_modified', sql.DateTime, index=True),
                  sql.Column('deleted', sql.Boolean),
                  sql.Column('content_type', sql.Unicode),
                  sql.Column('is_set', sql.Boolean),
                  sql.Column('sets', sql.Unicode)
                  )
        
        sql.Table('metadata', db,
                  sql.Column('metadata_id', sql.Integer, primary_key=True),
                  sql.Column('record_id', sql.Integer,
                             sql.ForeignKey('records.record_id'), index=True),
                  sql.Column('field', sql.String),
                  sql.Column('value', sql.Unicode),
                  sql.Column('reference', sql.Integer)
                  )
        
        db.create_all()
        return db


    def _get_record_id(self, id):
        result = None
        for record in self.records.select(
            self.records.c.name == id).execute():
            result = record['record_id']
        return result
    
    def get_record(self, id):
        result = None
        for record in self.records.select(
            self.records.c.name == id).execute():

            
            
            result = {'id': record['name'],
                      'deleted': record['deleted'],
                      'is_set': record['is_set'],
                      'content_type': record['content_type'],
                      'when_modified': record['when_modified'],
                      }
            break
        
        return result
                
    def get_metadata(self, id):
        result = {}
        for record in self.metadata.select(
            sql.and_(self.records.c.name == id,
                     self.metadata.c.record_id == self.records.c.record_id)).execute():

            result.setdefault(record['field'], []).append(record['value'])

        return result or None

    def get_sets(self, id):
        result = []

        for record in self.records.select(
            self.records.c.name == id).execute():
            result = record['sets'].strip().split(' ')
        
        return result

    def get_set(self, id):
        md = self.get_metadata(id)
        if not md:
            return {}
        result = {'name': md['name'][0],
                  'description': md['description'][0],
                  'id': id}
        return result

    def remove_content(self, id):
        rid = self._get_record_id(id)
        for result in self.records.delete(self.records.c.record_id == rid).execute():
            pass
        self._remove_metadata(rid)
        return True
    
    def add_content(self, id, sets, record_data, meta_data, assets_data):
        rowdata = {'name': record_data['id'],
                   'deleted': record_data['deleted'],
                   'is_set': record_data['is_set'],
                   'sets': u' %s ' % ' '.join(sets),
                   'content_type': record_data['content_type'],
                   'when_modified': record_data['when_modified']}
        result = self.records.insert(rowdata).execute()
        record_id = result.last_inserted_ids()[0]

        rowdata = []
                    
        self._add_metadata(record_id, meta_data)
        
        return record_id

    def _add_metadata(self, record_id, meta_data):
        rowdata = []
        
        for key, vals in meta_data.items():
            for val in vals:
                rowdata.append({'field': key,
                                'value': val,
                                'record_id': record_id})
        self.metadata.insert().execute(*rowdata)


    def _remove_metadata(self, record_id):
        for result in self.metadata.delete(self.metadata.c.record_id == record_id).execute():
            pass

    def add_set(self, set_id, name, description=None):
        if description is None:
            description = [u'']
        elif not isinstance(description, list):
            description = [description]

        record_data = {'id': set_id,
                       'content_type': u'set',
                       'deleted': False,
                       'sets': u'',
                       'is_set': True,
                       'when_modified': datetime.datetime.now()}
        meta_data  =  {'id':[set_id],
                       'name': [name],
                       'description': description}

        record_id = self._get_record_id(set_id)
        
        if record_id is None:
            # add a new set
            record_id = self.add_content(set_id, [], record_data, meta_data, {})
        else:
            # set is allready there, update the metadata
            self._remove_metadata(record_id)
            self._add_metadata(record_id, meta_data)

        return record_id
                         
    def remove_set(self, id):
        self.remove_content(id)

    def oai_sets(self, offset=0, batch_size=20):
        for row in self.records.select(self.records.c.is_set==True
            ).offset(offset).limit(batch_size).execute():
            result = {}
            for data in self.metadata.select(
                self.metadata.c.record_id==row['record_id']).execute():
                result[self.metadata.c.field] = self.metadata.c.value
            yield result

    def oai_query(self,
                  offset=0,
                  batch_size=20,
                  sets=[],
                  not_sets=[],
                  filter_sets=[],
                  from_date=None,
                  until_date=None,
                  identifier=None):

        if batch_size < 0:
            batch_size = 0

        # make sure until date is set, and not in future
        if until_date == None or until_date > datetime.datetime.now():
            until_date = datetime.datetime.now()


        query = self.records.select(self.records.c.is_set == False)

        # filter dates
        query.append_whereclause(self.records.c.when_modified < until_date)

        if not from_date is None:
            query.append_whereclause(self.records.c.when_modified > from_date)

        # filter sets

        setclauses = []
        for set_id in sets:
            setclauses.append(
                self.records.c.sets.like(u'%% %s %%' % set_id))
            
        if setclauses:
            query.append_whereclause(sql.or_(*setclauses))
            
        # extra filter sets
        
        filter_setclauses = []
        for set_id in filter_sets:
            filter_setclauses.append(
                self.records.c.sets.like(u'%% %s %%' % set_id))
            
        if filter_setclauses:
            query.append_whereclause(sql.or_(*filter_setclauses))

        # filter not_sets

        not_setclauses = []
        for set_id in not_sets:
            not_setclauses.append(
                self.records.c.sets.like(u'%% %s %%' % set_id))

            
        if not_setclauses:
            query.append_whereclause(sql.not_(
                sql.or_(*not_setclauses)))
            
            
        for row in query.distinct().offset(offset).limit(batch_size).execute():
            
            yield {'record': dict(row),
                   'metadata': self.get_metadata(row['name']),
                   'assets':{}}
