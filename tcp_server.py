import re
from enum import Enum
import socket
import sys
import operator
from threading import Thread
import traceback

# enum of Client Commands. Value is used as the maximal length
class CLIENT_CMD(Enum):
    USERNAME = r'^(?:(?!\x07\x08).){1,18}\x07\x08$', 20
    KEY_ID = r'^[0-9]{1,3}\x07\x08$', 5
    CONFIRMATION = r'^[0-9]{1,5}\x07\x08$', 7
    OK = r'^OK -?[0-9]{1,7} -?[0-9]{1,7}\x07\x08$', 12
    RECHARGING = r'RECHARGING\x07\x08$', 12
    FULL_POWER = r'FULL POWER\x07\x08$', 12
    MESSAGE = r'[^\x07\x08]{0,98}\x07\x08$', 100

# enum of Server Commands
class SERVER_CMD(Enum):
    CONFIRMATION = 1,
    MOVE = 2,
    TURN_LEFT = 3,
    TURN_RIGHT = 4,
    PICK_UP = 5,
    LOGOUT = 6,
    KEY_REQUEST = 7,
    OK = 8,
    LOGIN_FAILED = 9,
    SYNTAX_ERROR = 10,
    LOGIC_ERROR = 11,
    KEY_OUT_OF_RANGE_ERROR = 12

# table of Server/Client keys
KeyTable = [(23019, 32037), (32037, 29295), (18789, 13603), (16443, 29533), (18189, 21952)]

# remote bot representation class
class Bot:
    class Position:
        direction = ['n', 'e', 's', 'w']
        dir_index = 0

        def __init__(self, pos1, pos2) -> None:
            if pos1[0] > pos2[0]: self.dir_index = 3
            elif pos1[0] < pos2[0]: self.dir_index = 1
            elif pos1[1] > pos2[1]: self.dir_index = 2
            else: self.dir_index = 0

            self.x, self.y = pos2[0], pos2[1]

        def turn_right(self):
            self.dir_index = (self.dir_index + 1) % 4
        
        def turn_left(self):
            self.dir_index = self.direction.index(self.direction[self.dir_index - 1])
            
        def get_direction(self) -> str:
            return self.direction[self.dir_index]
        
        def get_position(self):
            return (self.x, self.y)

        def set_position(self, new_position):
            self.x = new_position[0]
            self.y = new_position[1]

    bot_position: Position = None

    def __init__(self, connection, address) -> None:
        self.bot_connection = Connection(connection, address)

    # authentication process
    def initialize(self):
        username = str(self.bot_connection.receive_command(CLIENT_CMD.USERNAME))
        char_sum = 0

        for c in username:
            char_sum += ord(c)

        resulting_hash = (char_sum * 1000) % 65536
        self.bot_connection.send_command('107 KEY REQUEST\a\b')
        bot_id = int(self.bot_connection.receive_command(CLIENT_CMD.KEY_ID))
        
        if bot_id < 0 or bot_id > 4:
            self.bot_connection.send_command('303 KEY OUT OF RANGE\a\b')
            print_colored('Key out of range error!', 'RED')
            self.bot_connection.terminate_connection()
            raise Exception()

        server_key = (resulting_hash + KeyTable[bot_id][0]) % 65536
        client_key = (resulting_hash + KeyTable[bot_id][1]) % 65536

        self.bot_connection.send_command(str(server_key) + '\a\b')
        client_key_received = self.bot_connection.receive_command(CLIENT_CMD.CONFIRMATION)

        if int(client_key) == int(client_key_received):
            self.bot_connection.send_command('200 OK\a\b')
        else:
            self.bot_connection.send_command('300 LOGIN FAILED\a\b')
            self.bot_connection.terminate_connection()

    # bypasses an obstacle; checks if (0,0) was reached
    def bypass_obstacle(self):
        print('obstacle occured!')
        self.turn_left()
        self.move_forward()
        if self.bot_position.get_position() == (0,0): 
            return True
        self.turn_right()
        self.move_forward()
        if self.bot_position.get_position() == (0,0): 
            return True
        self.move_forward()
        if self.bot_position.get_position() == (0,0): 
            return True
        self.turn_right()
        self.move_forward()
        if self.bot_position.get_position() == (0,0): 
            return True
        self.turn_left()
        return False

    # guides the bot to [0, 0]
    def start_search(self):
        pos = self.bot_position.get_position()
        while pos[0] != 0 or pos[1] != 0:
            direction_x = 'w'
            if pos[0] < 0: direction_x = 'e'
            if pos[0] != 0:
                while self.bot_position.get_direction() != direction_x:
                    self.turn_right()

                while self.bot_position.get_position()[0] != 0:
                    pos_ = pos
                    self.move_forward()
                    pos = self.bot_position.get_position()
                    if pos == pos_ or pos == (0,0):
                        break
            elif pos[1] != 0:
                if self.bypass_obstacle():
                    return

            if pos[1] != 0:
                direction_y = 'n'
                if pos[1] > 0: direction_y = 's'

                while self.bot_position.get_direction() != direction_y:
                    self.turn_right()
                            
                while self.bot_position.get_position()[1] != 0:
                    pos_ = pos
                    self.move_forward()
                    pos = self.bot_position.get_position()

                    if pos == pos_ or pos == (0,0):
                        break
            elif pos[0] != 0: 
                if self.bypass_obstacle():
                    return

    # picks a message; closes the connection
    def pick_message(self):
        self.bot_connection.send_command('105 GET MESSAGE\a\b')
        msg = self.bot_connection.receive_command(CLIENT_CMD.MESSAGE)
        print_colored(str(self.bot_connection.address) + ' -> MSG: ' + str(msg), 'GREEN')
        self.bot_connection.send_command('106 LOGOUT\a\b')
        self.bot_connection.terminate_connection()

    # estimates position and direction
    def get_current_position(self):
        pos1 = self.move_forward()
        pos2 = self.move_forward()
        if pos1 == pos2:
            self.bot_connection.send_command('103 TURN LEFT\a\b')
            self.bot_connection.receive_command(CLIENT_CMD.OK)
            pos1 = pos2
            pos2 = self.move_forward()
        self.bot_position = self.Position(pos1, pos2)

    #moves the robot one position forward
    def move_forward(self):
        self.bot_connection.send_command('102 MOVE\a\b')
        location = self.bot_connection.receive_command(CLIENT_CMD.OK)
        pos = (int(location.split(' ')[1]), int(location.split(' ')[2]))
        if self.bot_position != None:
            self.bot_position.set_position(pos)
        return pos

    #turns the robot left
    def turn_left(self):
        self.bot_connection.send_command('103 TURN LEFT\a\b')
        location = self.bot_connection.receive_command(CLIENT_CMD.OK)
        self.bot_position.turn_left()
        return (int(location.split(' ')[1]), int(location.split(' ')[2]))
    
    #turns the robot right
    def turn_right(self):
        self.bot_connection.send_command('104 TURN RIGHT\a\b')
        location = self.bot_connection.receive_command(CLIENT_CMD.OK)
        self.bot_position.turn_right()
        return (int(location.split(' ')[1]), int(location.split(' ')[2]))

# class handling client-server pair connection
class Connection:
    def __init__(self, connection, address) -> None:
        self.connection = connection
        self.address = address

    def send_command(self, msg: str):

        if not msg.endswith("\a\b"): msg += "\a\b"

        print_colored("\033[1m%s <- Sent: %s\033[0m" % (self.address, msg), 'CYAN')
        self.connection.sendall(bytes(str(msg), 'utf-8'))
    
    def terminate_connection(self):
        print_colored('Connection\'s closed!', 'RED')
        self.connection.close()

    # receive a command and handle possible RECHARGING
    def receive_command(self, cmd_expected) -> str:
        received = self.receive_command_inner(cmd_expected)

        if str(received) != 'RECHARGING\a\b':
            return str(received).rstrip('\a\b')

        self.receive_command_inner(CLIENT_CMD.FULL_POWER)

        return str(self.receive_command_inner(cmd_expected)).rstrip('\a\b')


    # receive and check a command
    def receive_command_inner(self, cmd_expected):
        received = ""

        if cmd_expected == CLIENT_CMD.FULL_POWER:
            self.connection.settimeout(5.0)
        else:
            self.connection.settimeout(1.0)
    
        while True:
            try:
                buffer = self.connection.recv(1)
            except:
                raise Exception("Connection timed out.")

            if not buffer:
                raise Exception("Empty symbol's received!")

            try:
                received += buffer.decode('utf-8')
            except:
                received += bytes(buffer).hex()
            if received.endswith("\a\b"):
                break

            if 'RECHARGING\a\b'.startswith(received):
                if len(received) == CLIENT_CMD.RECHARGING.value[1] - 1:
                    if not received.endswith("\a"):
                        raise Exception("Syntax error!")
                elif len(received) == CLIENT_CMD.RECHARGING.value[1]:
                    if not received.endswith("\a\b"):
                        raise Exception("Syntax error!")
            else:
                if len(received) == cmd_expected.value[1]:
                    if not received.endswith("\a\b"):
                        raise Exception('Syntax error!')

                if cmd_expected == CLIENT_CMD.RECHARGING:
                    print(CLIENT_CMD.OK.value[1])
                    if not 'RECHARGING\a\b'.startswith(received):
                        raise Exception('Syntax error!')
                elif cmd_expected == CLIENT_CMD.CONFIRMATION:
                    if not re.match("^[0-9]{1,5}", received):
                        raise Exception('Syntax error!')
                elif cmd_expected == CLIENT_CMD.KEY_ID:
                    if cmd_expected.value[1] > CLIENT_CMD.KEY_ID.value[1]:
                        raise Exception('Syntax error!')
                    try:
                        buf = int(received.rstrip('\a\b'))
                    except:
                        raise Exception('Syntax error!')
                elif cmd_expected == CLIENT_CMD.OK:
                    ok_args = received.rstrip("\a\b").split(" ")

                    if len(ok_args) > 3:
                        raise Exception('Syntax error!')
                    if len(ok_args[0]) > 0:
                        if not 'OK'.startswith(ok_args[0]):
                            raise Exception('Syntax error!')

                    try:
                        if len(ok_args) > 1 and ok_args[1] != "" and ok_args[1] != "-":
                            int(ok_args[1])
                        if len(ok_args) > 2 and ok_args[2] != "" and ok_args[2] != "-":
                            int(ok_args[2])
                    except Exception as e:
                        raise Exception('Syntax error!')

        print_colored("%s -> Received: %s" %
                      (self.address, repr(received)), 'BLUE')
        
        if not re.match(cmd_expected.value[0], received):
            if cmd_expected == CLIENT_CMD.FULL_POWER or received == 'FULL POWER\a\b':
                raise Exception('Logic error!')

        if received == 'RECHARGING\a\b':
            return received
        
        if len(received) == 0 and cmd_expected != CLIENT_CMD.MESSAGE:
            raise Exception("Input string length is 0")

        if cmd_expected == CLIENT_CMD.OK:
            if not re.match("^OK -?[0-9]{1,7} -?[0-9]{1,7}\x07\x08$", received):
                print(received)
                raise Exception("Syntax error!")
            return received
        elif cmd_expected == CLIENT_CMD.FULL_POWER:
            if received != 'FULL POWER\a\b':
                raise Exception("Syntax error!")
            return received

        elif cmd_expected == CLIENT_CMD.CONFIRMATION:
            if not re.match("^[0-9]{1,5}\x07\x08$", received):
                raise Exception("Syntax error!")
            return received

        return received


# custom print() function to add some style
def print_colored(text, mod, end_='\n'):
    class color_palette:
        RED = '\033[91m',
        BLUE = '\033[36m',
        PURPLE = '\033[95m',
        GREEN = '\033[92m',
        YELLOW = '\033[93m',
        BOLD = '\033[1m',
        CYAN = '\033[96m',
        END = '\033[0m'

    print(getattr(color_palette, mod, color_palette.RED)
          [0] + str(text) + color_palette.END, end=end_)

# thread server function
def server_thread(s: socket):
    while True:
        try:
            s.listen(0)  # backlog = 0 (number of pending connections)

            conn, addr = s.accept()

            print_colored('\nClinet ' + str(addr) + ' has connected.\n', 'PURPLE')

            bot = Bot(conn, addr)

            bot.initialize()
            print('')

            bot.get_current_position()
            print('')
                
            bot.start_search()
            print('')
                
            bot.pick_message()

        except Exception as e:
            print("SOMETHING WENT WRONG:", e)
            if str(e) == 'Syntax error!':
                bot.bot_connection.send_command('301 SYNTAX ERROR\a\b')
            elif str(e) == 'Logic error!':
                bot.bot_connection.send_command('302 LOGIC ERROR\a\b')
            bot.bot_connection.terminate_connection()
                
        

# program start
if __name__ == '__main__':
    port = 2022
    host = 'localhost'
    max_clients = 12

    if len(sys.argv) == 2:
        if sys.argv[1] == '--help':
            print_colored('\n\033[1mUsage: \033[0m', 'BLUE', '')
            print('\033[1mtcp_server.py <port> <host> <max clients>\033[0m\n')
            print_colored('Default Port:', 'BLUE', ' ')
            print(port)
            print_colored('Default Host:', 'BLUE', ' ')
            print(host)
            print_colored('Default Max Clients:', 'BLUE', ' ')
            print(max_clients, '\n')
            exit(0)
        else:
            print_colored('Use --help option to display the usage info.', 'YELLOW')
            exit(0)

    if len(sys.argv) == 4:
        port = int(sys.argv[1])
        host = sys.argv[2]
        max_clients = int(sys.argv[3])

    elif len(sys.argv) != 1:
        print_colored('Wrong program usage!\n', 'RED')
        print_colored('Use --help option to display the usage info.', 'YELLOW')
        exit(3)

    print_colored('\nBot Server is starting..', 'BOLD')
    print('Attempting to create a socket on %s:%d' % (host, port))

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # avoids the error Address already in use
        s.bind((host, port))
    except Exception as e:
        raise Exception('Failed to start the server due to the reason: ', e)

    print_colored('\nWaiting for connections', 'GREEN')

    for i in range(0, max_clients):
        t = Thread(target=server_thread, args=[s])
        t.start()