'''
The Salt Key backend api and interface used by the CLI. The Key class can be
used to manage salt keys directly without interfacing with the cli.
'''

# Import python modules
import os
import shutil
import fnmatch
# Import salt modules
import salt.crypt
import salt.utils
import salt.utils.event


class KeyCLI(object):
    '''
    Manage key cli operations
    '''
    def __init__(self, opts):
        self.opts = opts
        self.key = Key(opts)

    def list_status(self, status):
        '''
        Print out the keys under a named status
        '''
        keys = self.key.list_keys()
        if status.startswith('pre') or status.startswith('un'):
            salt.output.display_output(
                    {'minions_pre': keys['minions_pre']},
                    'key',
                    self.opts)

    def list_all(self):
        '''
        Print out all keys
        '''
        salt.output.display_output(
                self.key.list_keys(),
                'key',
                self.opts)

    def accept(self, match):
        '''
        Accept the keys matched
        '''
        matches = self.key.name_match(match)
        if not matches.get('minions_pre', False):
            print(
                'The key glob {0} dies not match any unaccepted keys.'.format(
                    match
                    )
                )
        after_match = self.key.accept(match)
        if 'minions_pre' in after_match:
            accepted = set(matches['minions_pre']).difference(
                    set(after_match['minions_pre'])
                    )
        else:
            accepted = matches['minions_pre']
        for key in accepted:
            print('Key for minion {0} accepted.'.format(key))

    def accept_all(self):
        '''
        Accept all keys
        '''
        self.accept('*')

    def delete(self, match):
        '''
        Delete the matched keys
        '''
        matches = self.key.name_match(match)
        if not self.opts.get('yes', False):
            print('The following keys are going to be deleted:')
            salt.output.display_output(
                    matches,
                    'key',
                    self.opts)
            veri = raw_input('Proceed? [n/Y] ')
            if veri.lower().startswith('n'):
                return
        self.key.delete_key(match)

    def delete_all(self):
        '''
        Delete all keys
        '''
        self.delete('*')

    def reject(self, match):
        '''
        Reject the matched keys
        '''
        matches = self.key.name_match(match)
        if not self.opts.get('yes', False):
            print('The following keys are going to be rejected:')
            salt.output.display_output(
                    matches,
                    'key',
                    self.opts)
            veri = raw_input('Proceed? [n/Y] ')
            if veri.lower().startswith('n'):
                return
        self.key.reject_key(match)

    def reject_all(self):
        '''
        Reject all keys
        '''
        self.reject('*')

    def print_key(self, match):
        '''
        Print out a single key
        '''
        matches = self.key.key_str(match)
        salt.output.display_output(
                matches,
                'key',
                self.opts)

    def print_all(self):
        '''
        Print out all managed keys
        '''
        self.print_key('*')

    def finger(self, match):
        '''
        Print out the fingerprints for the matched keys
        '''
        matches = self.key.finger(match)
        salt.output.display_output(
                matches,
                'key',
                self.opts)

    def finger_all(self):
        '''
        Print out all fingerprints
        '''
        matches = self.key.finger('*')
        salt.output.display_output(
                matches,
                'key',
                self.opts)

    def run(self):
        '''
        Run the logic for saltkey
        '''
        if self.opts['gen_keys']:
            salt.crypt.gen_keys(
                    self.opts['gen_keys_dir'],
                    self.opts['gen_keys'],
                    self.opts['keysize'])
            return
        if self.opts['list']:
            self.list_status(self.opts['list'])
        elif self.opts['list_all']:
            self.list_all()
        elif self.opts['print']:
            self.print_key(self.opts['print'])
        elif self.opts['print_all']:
            self.print_all()
        elif self.opts['accept']:
            self.accept(self.opts['accept'])
        elif self.opts['accept_all']:
            self.accept_all()
        elif self.opts['reject']:
            self.reject(self.opts['reject'])
        elif self.opts['reject_all']:
            self.reject_all()
        elif self.opts['delete']:
            self.delete_key(self.opts['delete'])
        elif self.opts['delete_all']:
            self.delete_all()
        elif self.opts['finger']:
            self.finger()
        elif self.opts['finger_all']:
            self.finger_all()
        else:
            self.list_all()


class Key(object):
    '''
    The object that encapsulates saltkey actions
    '''
    def __init__(self, opts):
        self.opts = opts
        self.event = salt.utils.event.MasterEvent(opts['sock_dir'])

    def _check_minions_directories(self):
        '''
        Return the minion keys directory paths
        '''
        minions_accepted = os.path.join(self.opts['pki_dir'], 'minions')
        minions_pre = os.path.join(self.opts['pki_dir'], 'minions_pre')
        minions_rejected = os.path.join(self.opts['pki_dir'],
                                        'minions_rejected')
        return minions_accepted, minions_pre, minions_rejected

    def check_master(self):
        '''
        Log if the master is not running
        '''
        if not os.path.exists(
                os.path.join(
                    self.opts['sock_dir'],
                    'publish_pull.ipc'
                    )
                ):
            return False
        return True

    def name_match(self, match, full=False):
        '''
        Accept a glob which to match the of a key and return the key's location
        '''
        if full:
            matches = self.list_all()
        else:
            matches = self.list_keys()
        ret = {}
        for status, keys in matches:
            for key in keys:
                if fnmatch(key, match):
                    if not status in ret:
                        ret[status] = []
                    ret[status].append(key)
        return ret

    def local_keys(self):
        '''
        Return a dict of local keys
        '''
        ret = {'local': []}
        for fn_ in os.listdir(self.opts['pki_dir']):
            if fn_.endswith('.pub') or fn_.endswith('.pem'):
                path = os.path.join(self.opts['pki_dir'], fn_)
                if os.path.isfile(path):
                    ret['local'].append(fn_)
        return ret

    def list_keys(self):
        '''
        Return a dict of managed keys and what the key status are
        '''
        acc, pre, rej = self._check_minions_directories()
        ret = {}
        for dir_ in acc, pre, rej:
            ret[os.path.basename(dir_)] = []
            for fn_ in os.listdir(dir_):
                ret[os.path.basename(dir_)].append(fn_)
        return ret

    def all_keys(self):
        '''
        Merge managed keys with local keys
        '''
        return self.list_keys().update(self.local_keys())

    def key_str(self, match):
        '''
        Return the specified public key or keys based on a glob
        '''
        ret = {}
        for status, keys in self.name_match(match):
            ret[status] = {}
            for key in keys:
                path = os.path.join(self.opts['pki_dir'], status, key)
                with open(path, 'r') as fp_:
                    ret[status][key] = fp_.read()
        return ret

    def key_str_all(self):
        '''
        Return all managed key strings
        '''
        ret = {}
        for status, keys in self.list_keys():
            ret[status] = {}
            for key in keys:
                path = os.path.join(self.opts['pki_dir'], status, key)
                with open(path, 'r') as fp_:
                    ret[status][key] = fp_.read()
        return ret

    def accept(self, match):
        '''
        Accept a specified host's public key based on name or keys based on
        glob
        '''
        matches = self.name_match(match)
        if 'minions_pre' in matches:
            for key in matches['minions_pre']:
                try:
                    shutil.move(
                            os.path.join(
                                self.opts['pki_dir'],
                                'minions_pre',
                                key),
                            os.path.join(
                                self.opts['pki_dir'],
                                'minions',
                                key)
                            )
                    eload = {'result': True,
                             'act': 'accept',
                             'id': key}
                    self.event.fire_event(eload, 'key')
                except (IOError, OSError):
                    pass
        return self.name_match(match)

    def accept_all(self):
        '''
        Accept all keys in pre
        '''
        keys = self.list_keys()
        for key in keys['minions_pre']:
            try:
                shutil.move(
                        os.path.join(
                            self.opts['pki_dir'],
                            'minions_pre',
                            key),
                        os.path.join(
                            self.opts['pki_dir'],
                            'minions',
                            key)
                        )
                eload = {'result': True,
                         'act': 'accept',
                         'id': key}
                self.event.fire_event(eload, 'key')
            except (IOError, OSError):
                pass
        return self.list_keys()

    def delete_key(self, match):
        '''
        Delete a single key or keys by glob
        '''
        for status, keys in self.name_match(match):
            for key in keys:
                try:
                    os.remove(os.path.join(self.opts['pki_dir'], status, key))
                except (OSError, IOError):
                    pass
        return self.list_keys()

    def delete_all(self):
        '''
        Delete all keys
        '''
        for status, keys in self.list_keys():
            for key in keys:
                try:
                    os.remove(os.path.join(self.opts['pki_dir'], status, key))
                except (OSError, IOError):
                    pass
        return self.list_keys()

    def reject(self, match):
        '''
        Reject a specified host's public key or keys based on a glob
        '''
        matches = self.name_match(match)
        if 'minions_pre' in matches:
            for key in matches['minions_pre']:
                try:
                    shutil.move(
                            os.path.join(
                                self.opts['pki_dir'],
                                'minions_pre',
                                key),
                            os.path.join(
                                self.opts['pki_dir'],
                                'minions_rejected',
                                key)
                            )
                    eload = {'result': True,
                             'act': 'reject',
                             'id': key}
                    self.event.fire_event(eload, 'key')
                except (IOError, OSError):
                    pass
        return self.name_match(match)

    def reject_all(self):
        '''
        Reject all keys in pre
        '''
        keys = self.list_keys()
        for key in keys['minions_pre']:
            try:
                shutil.move(
                        os.path.join(
                            self.opts['pki_dir'],
                            'minions_pre',
                            key),
                        os.path.join(
                            self.opts['pki_dir'],
                            'minions_rejected',
                            key)
                        )
                eload = {'result': True,
                         'act': 'reject',
                         'id': key}
                self.event.fire_event(eload, 'key')
            except (IOError, OSError):
                pass
        return self.list_keys()

    def finger(self, match):
        '''
        Return the fingerprint for a specified key
        '''
        matches = self.name_match(match, True)
        ret = {}
        for status, keys in matches.items():
            ret[status] = {}
            for key in keys:
                ret[status][key] = salt.utils.pem_finger(key)
        return ret

    def finger_all(self):
        '''
        Return fingerprins for all keys
        '''
        ret = {}
        for status, keys in self.list_keys():
            ret[status] = {}
            for key in keys:
                ret[status][key] = salt.utils.pem_finger(key)
        return ret
