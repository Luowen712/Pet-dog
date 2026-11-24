import time



def now_ms()-> int:
    """
    获取当前时间戳，精确到毫秒
    
    Returns:
        int: 当前时间戳，单位为毫秒
    """
    return int(time.time() * 1000)  # 将当前时间戳（秒）转换为毫秒并返回整数



def ok(data=None,message:str='ok')-> dict:
    """构造成功响应外壳：code 固定为 0，并带上毫秒时间戳。"""
    return {'code': 0, 'message': message, 'data': data, 'timestamp': now_ms()}



def fail(code: int,message:str,data=None)-> dict:
    """构造失败响应外壳：写入业务错误码与提示文案。"""
    return {'code': code, 'message': message, 'data': data, 'timestamp': now_ms()}