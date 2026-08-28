import logging
import os
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
import json
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

bearer_scheme = HTTPBearer()

def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    """ Dependency to check jwt validity and log authentication and errors"""
    token = credentials.credentials

    try: 
        payload = jwt.decode(token, SECRET_KEY, algorithms = [ALGORITHM])
        username = payload.get('sub')
        session_id = payload.get('session_id')

        if not username:
            # Log structural failure
            logger.warning("Auth Check Failed: Token is missing 'sub' (subject) claim.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token claims",
            )
            
        # Log successful authentication trace
        logger.info(f"Auth Check Success: User '{username}' successfully verified at {datetime.now(timezone.utc)}")
        return payload

    except jwt.ExpiredSignatureError:
        logger.warning(f"Auth Check Failed: Attempted login with an expired token.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Token has expired"
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"Auth Check Failed: Invalid token provided. Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid authentication token"
        )


