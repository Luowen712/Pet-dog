import time

def now_ms()-> int:


    """
    获取当前时间戳，精确到毫秒
    
    Returns:
        int: 当前时间戳，单位为毫秒
    """
    return int(time.time() * 1000)  # 将当前时间戳（秒）转换为毫秒并返回整数

def ok(data=None,message:str='ok')-> dict:

    return {'code': 0, 'message': message, 'data': data, 'timestamp': now_ms()}

def fail(code: int,message:str,data=None)-> dict:

    return {'code': code, 'message': message, 'data': data, 'timestamp': now_ms()}